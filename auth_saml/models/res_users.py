# Copyright (C) 2010-2016,2018 XCG Consulting <http://odoo.consulting>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from typing import Set

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessDenied, ValidationError

import lasso
import passlib

_logger = logging.getLogger(__name__)


class ResUser(models.Model):
    """Add SAML login capabilities to Odoo users.
    """

    _inherit = "res.users"

    saml_provider_id = fields.Many2one(
        "auth.saml.provider", string="SAML Provider"
    )
    saml_uid = fields.Char("SAML User ID", help="SAML Provider user_id")

    _sql_constraints = [
        (
            "uniq_users_saml_provider_saml_uid",
            "unique(saml_provider_id, saml_uid)",
            "SAML UID must be unique per provider",
        )
    ]

    @api.multi
    def _auth_saml_validate(self, provider_id, token):
        """ return the validation data corresponding to the access token """

        p = self.env["auth.saml.provider"].browse(provider_id)

        # we are not yet logged in, so the userid cannot have access to the
        # fields we need yet
        login = p.sudo()._get_lasso_for_provider()
        matching_attribute = p._get_matching_attr_for_provider()

        try:
            login.processAuthnResponseMsg(token)
        except (lasso.DsError, lasso.ProfileCannotVerifySignatureError):
            raise Exception("Lasso Profile cannot verify signature")
        except lasso.ProfileStatusNotSuccessError:
            raise Exception("Profile Status Not Success Error")
        except lasso.Error as e:
            raise Exception(repr(e))

        try:
            login.acceptSso()
        except lasso.Error as error:
            raise Exception(
                "Invalid assertion : %s" % lasso.strError(error[0])
            )

        attrs = {}

        for att_statement in login.assertion.attributeStatement:
            for attribute in att_statement.attribute:
                name = None
                lformat = lasso.SAML2_ATTRIBUTE_NAME_FORMAT_BASIC
                nickname = None
                try:
                    name = attribute.name
                except Exception:
                    _logger.warning(
                        "sso_after_response: error decoding name \
                        of attribute %s"
                        % attribute.dump()
                    )
                else:
                    if attribute.nameFormat:
                        lformat = attribute.nameFormat
                    if attribute.friendlyName:
                        nickname = attribute.friendlyName
                    if name:
                        if lformat:
                            if nickname:
                                key = (name, lformat, nickname)
                            else:
                                key = (name, lformat)
                        else:
                            key = name
                    attrs[key] = list()
                    for value in attribute.attributeValue:
                        content = [a.exportToXml() for a in value.any]
                        content = "".join(content)
                        attrs[key].append(content)

        matching_value = None
        for k in attrs:
            if isinstance(k, tuple) and k[0] == matching_attribute:
                matching_value = attrs[k][0]
                break

        if not matching_value and matching_attribute == "subject.nameId":
            matching_value = login.assertion.subject.nameId.content

        elif not matching_value and matching_attribute != "subject.nameId":
            raise Exception(
                "Matching attribute %s not found in user attrs: %s"
                % (matching_attribute, attrs)
            )

        validation = {"user_id": matching_value}
        return validation

    @api.multi
    def _auth_saml_signin(self, provider, validation, saml_response):
        """ retrieve and sign into openerp the user corresponding to provider
        and validated access token

            :param provider: saml provider id (int)
            :param validation: result of validation of access token (dict)
            :param saml_response: saml parameters response from the IDP
            :return: user login (str)
            :raise: openerp.exceptions.AccessDenied if signin failed

            This method can be overridden to add alternative signin methods.
        """
        token_osv = self.env["auth_saml.token"]
        saml_uid = validation["user_id"]

        user_ids = self.search(
            [("saml_uid", "=", saml_uid), ("saml_provider_id", "=", provider)]
        )

        if not user_ids:
            raise AccessDenied()

        # TODO replace assert by proper raise... asserts do not execute in
        # production code...
        assert len(user_ids) == 1
        user = user_ids[0]

        # now find if a token for this user/provider already exists
        token_ids = token_osv.search(
            [("saml_provider_id", "=", provider), ("user_id", "=", user.id)]
        )

        if token_ids:
            token_ids.write({"saml_access_token": saml_response})
        else:
            token_osv.create(
                {
                    "saml_access_token": saml_response,
                    "saml_provider_id": provider,
                    "user_id": user.id,
                }
            )

        return user.login

    @api.model
    def auth_saml(self, provider, saml_response):

        validation = self._auth_saml_validate(provider, saml_response)

        # required check
        if not validation.get("user_id"):
            raise AccessDenied()

        # retrieve and sign in user
        login = self._auth_saml_signin(provider, validation, saml_response)

        if not login:
            raise AccessDenied()

        # return user credentials
        return self.env.cr.dbname, login, saml_response

    @api.model
    def check_credentials(self, token):
        """Override to handle SAML auths.

        The token can be a password if the user has used the normal form...
        but we are more interested in the case when they are tokens
        and the interesting code is inside the "except" clause.
        """

        try:
            # Attempt a regular login (via other auth addons) first.
            super(ResUser, self).check_credentials(token)

        except (AccessDenied, passlib.exc.PasswordSizeError):
            # since normal auth did not succeed we now try to find if the user
            # has an active token attached to his uid
            res = (
                self.env["auth_saml.token"]
                .sudo()
                .search(
                    [
                        ("user_id", "=", self.env.user.id),
                        ("saml_access_token", "=", token),
                    ]
                )
            )

            # if the user is not found we re-raise the AccessDenied
            if not res:
                # TODO: maybe raise a defined exception instead of the last
                # exception that occurred in our execution frame
                raise

    # TODO check if there is an error on create

    @api.multi
    def write(self, vals):
        """Override to clear out the user's password when setting an SAML user
        ID (as they can't cohabit).
        """

        # Clear out the pass when:
        # - An SAML ID is being set.
        # - The user is not the Odoo admin.
        # - The "allow both" setting is disabled.
        if (
            vals
            and vals.get("saml_uid")
            and self.id is not SUPERUSER_ID
            and not self._allow_saml_and_password()
        ):
            # adding password/password crypt does not work
            for k in ("password", "password_crypt"):
                if k in vals:
                    vals.pop(k)
            self.env.cr.execute(
                "UPDATE res_users SET password='', password_crypt='' WHERE "
                "id=%s",
                (self.id,),
            )
            self.invalidate_cache()

        return super(ResUser, self).write(vals)

    @api.model
    def _saml_allowed_user_ids(self) -> Set[int]:
        """Users that can have a password even if the option to disallow it is set.
        It includes superuser and the admin if it exists.
        """
        allowed_users = {SUPERUSER_ID}
        user_admin = self.env.ref("base.user_admin", False)
        if user_admin:
            allowed_users.add(user_admin.id)
        return allowed_users

    @api.model
    def _allow_saml_and_password(self):

        return self.env["res.config.settings"].allow_saml_and_password()

    def _set_encrypted_password(self, encrypted):
        """Redefine auth_crypt method to block password change as it uses
        a cursor to do it and the python constrains would not be called
        """
        if (
            not self._allow_saml_and_password()
            and self.saml_uid
            and self.id is not SUPERUSER_ID
        ):
            raise ValidationError(
                _(
                    "This database disallows users to have both passwords "
                    "and SAML IDs. Error for login {}."
                ).format(self.login)
            )
        super(ResUser, self)._set_encrypted_password(encrypted)

    def _inverse_password(self):
        """Inverse method of the password field."""
        # Redefine base method to block setting password on users with SAML ids
        # And also to be able to set password to a blank value
        if not self._allow_saml_and_password():
            saml_users = self.filtered(
                lambda user: user.sudo().saml_uid
                and self.id not in self._saml_allowed_user_ids()
                and user.password
            )
            if saml_users:

                # same error as an api.constrains because it is a constraint.
                # a standard constrains would require the use of SQL as the
                # password field is obfuscated by the base module.
                raise ValidationError(
                    _(
                        "This database disallows users to "
                        "have both passwords and SAML IDs. "
                        "Error for logins %s."
                    )
                    % (", ".join(saml_users.mapped("login")),)
                )
        # handle setting password to NULL
        blank_password_users = self.filtered(
            lambda user: user.password is False
        )
        non_blank_password_users = self - blank_password_users
        if non_blank_password_users:
            # pylint: disable=protected-access
            super(ResUser, non_blank_password_users)._inverse_password()
        if blank_password_users:
            # similar to what Odoo does in Users._set_encrypted_password
            self.env.cr.execute(
                "UPDATE res_users SET password = NULL WHERE id IN %s",
                (tuple(blank_password_users.ids),),
            )
            self.invalidate_cache(["password"], blank_password_users.ids)
        return

    def allow_saml_and_password_changed(self):
        """Called after the parameter is changed."""
        if not self._allow_saml_and_password():
            # sudo because the user doing the parameter change might not have
            # the right to search or write users
            users_to_blank_password = self.sudo().search(
                [
                    "&",
                    ("saml_uid", "!=", False),
                    ("id", "not in", list(self._saml_allowed_user_ids())),
                ]
            )
            _logger.debug(
                "Removing password from %s user(s)",
                len(users_to_blank_password),
            )
            users_to_blank_password.write({
                "password": False, "password_crypt": False,
            })
