from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase
from django.test import override_settings
from unittest.mock import patch
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient
from rest_framework.test import APIRequestFactory
from rest_framework.test import force_authenticate

from core.api.authentication import _get_keycloak_settings
from core.api.authentication import decode_and_validate_keycloak_token
from core.api.authentication import KeycloakClaims
from core.api.authentication import KeycloakJWTAuthentication
from core.api.authentication import KeycloakTokenUser
from core.api.utils import access_control
from core.api.v1.views import auth_me_view


class AccessControlTests(SimpleTestCase):
    def test_keycloak_user_project_access_and_labs(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="juan",
            projects=[
                {
                    "id": "mepram",
                    "labs": ["lab1", "lab2"],
                    "role": "view",
                    "project_role": "view",
                    "lab_roles": [
                        {"lab": "lab1", "role": "admin"},
                        {"lab": "lab2", "role": "view"},
                    ],
                },
                {"id": "relecov", "labs": ["lab3"], "role": "admin"},
            ],
        )

        self.assertTrue(access_control.has_project_access(user, "mepram"))
        self.assertFalse(access_control.has_project_write_access(user, "mepram"))
        self.assertTrue(
            access_control.has_project_lab_write_access(user, "mepram", "lab1")
        )
        self.assertFalse(
            access_control.has_project_lab_write_access(user, "mepram", "lab2")
        )
        self.assertTrue(access_control.has_project_write_access(user, "relecov"))
        self.assertEqual(access_control.get_project_labs(user, "relecov"), ["lab3"])

    def test_project_access_is_derived_from_standard_group_paths(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="daniel",
            groups=[
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        )

        projects = access_control.get_user_projects(user)

        self.assertEqual(
            projects,
            [
                {
                    "id": "mepram",
                    "labs": ["lab1"],
                    "role": None,
                    "effective_role": "admin",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab1", "role": "admin"}],
                    "source_groups": ["/use-cases/mepram/labs/lab1/admin"],
                },
                {
                    "id": "relecov",
                    "labs": ["lab2"],
                    "role": None,
                    "effective_role": "view",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab2", "role": "view"}],
                    "source_groups": ["/use-cases/relecov/labs/lab2/viewer"],
                },
            ],
        )

    def test_non_canonical_project_groups_are_rejected(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="legacy-projects",
            groups=[
                "/projects/mepram/admin",
                "/projects/mepram/labs/lab1",
            ],
        )

        with self.assertRaisesMessage(
            access_control.GroupParsingError,
            "Malformed group path '/projects/mepram/admin'",
        ):
            access_control.get_user_projects(user)

    def test_keycloak_authorization_model_infers_project_view_from_labs(self):
        authorization = access_control.build_keycloak_authorization(
            subject="user-1",
            username="daniel",
            groups_claim=[
                "/superusers",
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        )

        self.assertEqual(
            authorization["authorization"],
            {
                "id": "user-1",
                "username": "daniel",
                "superuser": True,
                "projects": {
                    "mepram": {
                        "project_role": "view",
                        "labs": {"lab1": "admin"},
                    },
                    "relecov": {
                        "project_role": "view",
                        "labs": {"lab2": "view"},
                    },
                },
            },
        )

    def test_projects_claim_is_used_only_as_legacy_fallback(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="legacy",
            projects=[{"id": "mepram", "labs": ["lab1"], "role": "admin"}],
        )

        self.assertEqual(
            access_control.get_user_projects(user),
            [
                {
                    "id": "mepram",
                    "labs": ["lab1"],
                    "role": "admin",
                    "effective_role": "admin",
                    "project_role": "admin",
                    "lab_roles": [],
                    "source_groups": [],
                }
            ],
        )

    def test_multi_project_user_requires_explicit_project_route(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="juan",
            projects=[
                {"id": "mepram", "labs": ["lab1"], "role": "view"},
                {"id": "relecov", "labs": ["lab3"], "role": "admin"},
            ],
        )

        with self.assertRaises(PermissionDenied):
            access_control.get_user_project_code(user)


class KeycloakAuthenticationTests(SimpleTestCase):
    def setUp(self):
        self.payload = {
            "sub": "user_123",
            "preferred_username": "juan",
            "groups": [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
            "iss": "https://keycloak.local/realms/pathocore",
            "aud": "pathocore-api",
            "exp": 9999999999,
        }

    @patch(
        "core.api.authentication._get_keycloak_settings",
        return_value={
            "issuer": "https://keycloak.local/realms/pathocore",
            "jwks_url": "https://keycloak.local/realms/pathocore/protocol/openid-connect/certs",
            "audience": "pathocore-api",
            "client_id": "pathocore-api",
            "jwks_cache_ttl_seconds": 300,
            "jwks_timeout_seconds": 5,
        },
    )
    @patch("core.api.authentication._get_signing_key", return_value="public-key")
    @patch(
        "core.api.authentication.jwt.decode",
        return_value={
            "sub": "user_123",
            "preferred_username": "juan",
            "groups": [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
            "iss": "https://keycloak.local/realms/pathocore",
            "aud": "pathocore-api",
            "exp": 9999999999,
        },
    )
    @patch(
        "core.api.authentication.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "kid-1"},
    )
    def test_decode_token_returns_expected_payload(
        self,
        header_mock,
        decode_mock,
        signing_key_mock,
        settings_mock,
    ):
        auth = KeycloakJWTAuthentication()

        payload = auth._decode_token("token-value")

        self.assertEqual(payload["sub"], "user_123")
        self.assertEqual(payload["preferred_username"], "juan")
        self.assertEqual(
            payload["groups"],
            [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        )

    @patch(
        "core.api.authentication._get_keycloak_settings",
        return_value={
            "issuer": "https://keycloak.local/realms/pathocore",
            "jwks_url": "https://keycloak.local/realms/pathocore/protocol/openid-connect/certs",
            "audience": "pathocore-api",
            "client_id": "pathocore-api",
            "jwks_cache_ttl_seconds": 300,
            "jwks_timeout_seconds": 5,
        },
    )
    @patch("core.api.authentication._get_signing_key", return_value="public-key")
    @patch("core.api.authentication.jwt.decode")
    @patch(
        "core.api.authentication.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "kid-1"},
    )
    def test_authenticate_attaches_verified_claims_to_request(
        self,
        header_mock,
        decode_mock,
        signing_key_mock,
        settings_mock,
    ):
        decode_mock.return_value = self.payload
        request = APIRequestFactory().get(
            "/v1/auth/me",
            HTTP_AUTHORIZATION="Bearer token-value",
        )

        user, auth = KeycloakJWTAuthentication().authenticate(request)

        self.assertEqual(user.id, "user_123")
        self.assertEqual(user.username, "juan")
        self.assertEqual(
            user.groups,
            [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        )
        self.assertEqual(
            user.projects,
            [
                {
                    "id": "mepram",
                    "labs": ["lab1"],
                    "role": None,
                    "effective_role": "admin",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab1", "role": "admin"}],
                    "source_groups": ["/use-cases/mepram/labs/lab1/admin"],
                },
                {
                    "id": "relecov",
                    "labs": ["lab2"],
                    "role": None,
                    "effective_role": "view",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab2", "role": "view"}],
                    "source_groups": ["/use-cases/relecov/labs/lab2/viewer"],
                },
            ],
        )
        self.assertEqual(auth, self.payload)

    @patch(
        "core.api.authentication._get_keycloak_settings",
        return_value={
            "issuer": "https://keycloak.local/realms/pathocore",
            "jwks_url": "https://keycloak.local/realms/pathocore/protocol/openid-connect/certs",
            "audience": "pathocore-api",
            "client_id": "pathocore-api",
            "jwks_cache_ttl_seconds": 300,
            "jwks_timeout_seconds": 5,
        },
    )
    @patch("core.api.authentication._get_signing_key", return_value="public-key")
    @patch("core.api.authentication.jwt.decode")
    @patch(
        "core.api.authentication.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "kid-1"},
    )
    def test_reusable_decoder_returns_normalized_claims(
        self,
        header_mock,
        decode_mock,
        signing_key_mock,
        settings_mock,
    ):
        decode_mock.return_value = self.payload

        claims = decode_and_validate_keycloak_token("token-value")

        self.assertEqual(claims.subject, "user_123")
        self.assertEqual(claims.username, "juan")
        self.assertEqual(
            claims.groups,
            [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        )
        self.assertEqual(
            claims.projects,
            [
                {
                    "id": "mepram",
                    "labs": ["lab1"],
                    "role": None,
                    "effective_role": "admin",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab1", "role": "admin"}],
                    "source_groups": ["/use-cases/mepram/labs/lab1/admin"],
                },
                {
                    "id": "relecov",
                    "labs": ["lab2"],
                    "role": None,
                    "effective_role": "view",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab2", "role": "view"}],
                    "source_groups": ["/use-cases/relecov/labs/lab2/viewer"],
                },
            ],
        )

    @patch(
        "core.api.authentication._get_keycloak_settings",
        return_value={
            "issuer": "https://keycloak.local/realms/pathocore",
            "jwks_url": "https://keycloak.local/realms/pathocore/protocol/openid-connect/certs",
            "audience": "pathocore-api",
            "client_id": "pathocore-api",
            "jwks_cache_ttl_seconds": 300,
            "jwks_timeout_seconds": 5,
        },
    )
    @patch("core.api.authentication._get_signing_key", return_value="public-key")
    @patch(
        "core.api.authentication.jwt.decode",
        return_value={
            "groups": ["/use-cases/mepram/labs/lab1/admin"],
            "iss": "https://keycloak.local/realms/pathocore",
            "aud": "pathocore-api",
            "exp": 9999999999,
        },
    )
    @patch(
        "core.api.authentication.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "kid-1"},
    )
    def test_decoder_rejects_token_without_subject_claim(
        self,
        header_mock,
        decode_mock,
        signing_key_mock,
        settings_mock,
    ):
        with self.assertRaisesMessage(
            AuthenticationFailed,
            "Token is missing required claim: sub",
        ):
            decode_and_validate_keycloak_token("token-value")

    @patch(
        "core.api.authentication._get_keycloak_settings",
        return_value={
            "issuer": "https://keycloak.local/realms/pathocore",
            "jwks_url": "https://keycloak.local/realms/pathocore/protocol/openid-connect/certs",
            "audience": "pathocore-api",
            "client_id": "pathocore-api",
            "jwks_cache_ttl_seconds": 300,
            "jwks_timeout_seconds": 5,
        },
    )
    @patch("core.api.authentication._get_signing_key", return_value="public-key")
    @patch(
        "core.api.authentication.jwt.decode",
        return_value={
            "sub": "user_123",
            "preferred_username": "juan",
            "groups": ["/use-cases/mepram/labs/lab1/editor"],
            "iss": "https://keycloak.local/realms/pathocore",
            "aud": "pathocore-api",
            "exp": 9999999999,
        },
    )
    @patch(
        "core.api.authentication.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "kid-1"},
    )
    def test_decoder_rejects_malformed_groups(
        self,
        header_mock,
        decode_mock,
        signing_key_mock,
        settings_mock,
    ):
        with self.assertRaisesMessage(
            AuthenticationFailed,
            "Malformed groups claim: Unknown role 'editor'",
        ):
            decode_and_validate_keycloak_token("token-value")

    @patch("core.api.authentication.settings")
    def test_keycloak_settings_are_loaded_from_required_env_names(
        self,
        settings_mock,
    ):
        settings_mock.KEYCLOAK_ISSUER = (
            "http://127.0.0.1:8090/realms/ciberisciii_datahub"
        )
        settings_mock.KEYCLOAK_JWKS_URL = (
            "http://127.0.0.1:8090/realms/ciberisciii_datahub/"
            "protocol/openid-connect/certs"
        )
        settings_mock.KEYCLOAK_AUDIENCE = "pathocore-api"
        settings_mock.KEYCLOAK_CLIENT_ID = "pathocore-web"
        settings_mock.KEYCLOAK_JWKS_CACHE_TTL_SECONDS = 300
        settings_mock.KEYCLOAK_JWKS_TIMEOUT_SECONDS = 5

        config = _get_keycloak_settings()

        self.assertEqual(
            config["issuer"],
            "http://127.0.0.1:8090/realms/ciberisciii_datahub",
        )
        self.assertEqual(
            config["jwks_url"],
            (
                "http://127.0.0.1:8090/realms/ciberisciii_datahub/"
                "protocol/openid-connect/certs"
            ),
        )
        self.assertEqual(config["audience"], "pathocore-api")
        self.assertEqual(config["client_id"], "pathocore-api")


class AuthMeViewTests(SimpleTestCase):
    def test_auth_me_returns_verified_token_payload_and_group_derived_projects(self):
        request = APIRequestFactory().get("/v1/auth/me")
        user = KeycloakTokenUser(
            subject="user_123",
            username="juan",
            groups=[
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
            token_payload={"sub": "user_123", "preferred_username": "juan"},
        )
        token_payload = {
            "sub": "user_123",
            "preferred_username": "juan",
            "groups": [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        }
        force_authenticate(request, user=user, token=token_payload)

        response = auth_me_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["id"], "user_123")
        self.assertEqual(
            response.data["user"]["groups"],
            [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
        )
        self.assertEqual(
            response.data["user"]["projects"],
            [
                {
                    "id": "mepram",
                    "labs": ["lab1"],
                    "role": None,
                    "effective_role": "admin",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab1", "role": "admin"}],
                    "source_groups": ["/use-cases/mepram/labs/lab1/admin"],
                },
                {
                    "id": "relecov",
                    "labs": ["lab2"],
                    "role": None,
                    "effective_role": "view",
                    "project_role": None,
                    "lab_roles": [{"lab": "lab2", "role": "view"}],
                    "source_groups": ["/use-cases/relecov/labs/lab2/viewer"],
                },
            ],
        )
        self.assertEqual(response.data["token"]["preferred_username"], "juan")


@override_settings(ROOT_URLCONF="conf.urls", ALLOWED_HOSTS=["testserver", "localhost"])
class TestKeycloakRequestFlow(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "sub": "user_123",
            "preferred_username": "juan",
            "groups": [
                "/use-cases/mepram/labs/lab1/admin",
                "/use-cases/relecov/labs/lab2/viewer",
            ],
            "iss": "http://127.0.0.1:8090/realms/ciberisciii_datahub",
            "aud": "pathocore-api",
            "exp": 9999999999,
        }

    @patch("core.api.authentication.decode_and_validate_keycloak_token")
    def test_get_auth_me_validates_bearer_token_before_view_logic(
        self,
        decode_mock,
    ):
        decode_mock.return_value = KeycloakClaims(
            raw_token="token-value",
            payload=self.payload,
        )

        response = self.client.get(
            "/v1/auth/me",
            HTTP_AUTHORIZATION="Bearer token-value",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], "user_123")
        decode_mock.assert_called_once_with("token-value")

    @patch("core.api.authentication.decode_and_validate_keycloak_token")
    def test_invalid_bearer_token_is_rejected_before_view_logic(
        self,
        decode_mock,
    ):
        decode_mock.side_effect = AuthenticationFailed("Invalid token audience")

        response = self.client.get(
            "/v1/auth/me",
            HTTP_AUTHORIZATION="Bearer token-value",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid token audience")
        decode_mock.assert_called_once_with("token-value")

    @patch("core.api.authentication.decode_and_validate_keycloak_token")
    def test_post_endpoint_uses_same_bearer_validation_path(
        self,
        decode_mock,
    ):
        decode_mock.return_value = KeycloakClaims(
            raw_token="token-value",
            payload=self.payload,
        )

        response = self.client.post(
            "/v1/variants/ingest",
            data={},
            format="json",
            HTTP_AUTHORIZATION="Bearer token-value",
        )

        self.assertEqual(response.status_code, 400)
        decode_mock.assert_called_once_with("token-value")
