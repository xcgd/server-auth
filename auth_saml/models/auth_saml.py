# Copyright (C) 2020 GlodoUK <https://www.glodo.uk>
# Copyright (C) 2010-2020 XCG Consulting <http://odoo.consulting>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import json
import logging

from odoo import api, fields, models

import lasso

_logger = logging.getLogger(__name__)


class AuthSamlProvider(models.Model):
    """Class defining the configuration values of a SAML2 provider"""

    _name = "auth.saml.provider"
    _description = "SAML2 provider"
    _order = "sequence, name"

    # Name of the OAuth2 entity, authentic, xcg...
    name = fields.Char("Provider Name", required=True, index=True)
    idp_metadata = fields.Text(
        string="Identity Provider Metadata",
        help=(
            "Configuration for this Identity Provider. Supplied by the"
            " provider, in XML format."
        ),
)
    sp_metadata = fields.Text("SP Configuration")
    sp_pkey = fields.Text(
        string="SP Private key",
        help="Private key of our service provider (this odoo server)",
	# TODO check what this does
	# field in binary
        #attachment=True,
    )
    matching_attribute = fields.Char(
        string="Identity Provider matching attribute",
        default="subject.nameId",
        required=True,
        help=(
            "Attribute to look for in the returned IDP response to match"
            " against an Odoo user."
        ),
    )

    enabled = fields.Boolean("Enabled", default=False)
    sequence = fields.Integer("Sequence", index=True)
    css_class = fields.Char(
        string="Button Icon CSS class",
        help="Add a CSS class that serves you to style the login button.",
    )
    body = fields.Char(string="Button Description")
    autoredirect = fields.Boolean(
        "Autoredirect",
        default=False,
        help="Only the provider with the most priority will be automatically"
        " redirected",
    )

    def _get_lasso_for_provider(self):
        """internal helper to get a configured lasso.Login object for the
        given provider id"""

        # TODO: we should cache those results somewhere because it is
        # really costly to always recreate a login variable from buffers
        server = lasso.Server.newFromBuffers(self.sp_metadata, self.sp_pkey)

        # Requests are SHA1-signed by default -> Ask for SHA-256.
        server.signatureMethod = lasso.SIGNATURE_METHOD_RSA_SHA256

        server.addProviderFromBuffer(
            lasso.PROVIDER_ROLE_IDP, self.idp_metadata
        )
        return lasso.Login(server)

    def _get_matching_attr_for_provider(self):
        """internal helper to fetch the matching attribute for this SAML
        provider. Returns a unicode object.
        """

        self.ensure_one()

        return self.matching_attribute

    def _get_auth_request(self, state):
        """build an authentication request and give it back to our client
        """

        self.ensure_one()

        login = self._get_lasso_for_provider()

        # This part MUST be performed on each call and cannot be cached
        login.initAuthnRequest()
        login.request.nameIdPolicy.format = None
        login.request.nameIdPolicy.allowCreate = True
        login.msgRelayState = json.dumps(state)
        login.buildAuthnRequestMsg()

        # msgUrl is a fully encoded url ready for redirect use
        # obtained after the buildAuthnRequestMsg() call
        return login.msgUrl
