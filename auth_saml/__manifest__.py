# Copyright (C) 2020 GlodoUK <https://www.glodo.uk/>
# Copyright (C) 2010-2020 XCG Consulting <http://odoo.consulting>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "SAML2 Authentication",
    "version": "13.0.1.0.0",
    "category": "Tools",
    "author": "XCG Consulting, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/server-auth",
    "license": "AGPL-3",
    "depends": ["base_setup", "web"],
    "data": [
        "data/ir_config_parameter.xml",
        "security/ir.model.access.csv",
        "views/auth_saml.xml",
        "views/base_settings.xml",
        "views/res_users.xml",
    ],
    "demo": ["demo/auth_saml.xml"],
    "installable": True,
    "auto_install": False,
    "external_dependencies": {"python": ["lasso"]},  # ≥2.6.0
    "development_status": "beta",
}
