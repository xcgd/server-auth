Changelog
=========

10.0.2.0.0
----------

- Sign auth requests with SHA-256 instead of SHA-1. ``lasso >= 2.6.0`` is
  expected.

10.0.1.0.0
----------

- Port to Odoo 10 based on version 11.0.1.0.2.

11.0.1.0.2
----------

- Fix setting saml_uid on user with password
- Block setting password when not allowed

11.0.1.0.1
----------

Viewing SAML providers does not need to be in debug mode anymore.
