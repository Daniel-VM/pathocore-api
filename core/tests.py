import base64
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient
from rest_framework.test import APIRequestFactory
from rest_framework.test import force_authenticate

from core.api.authentication import _get_keycloak_settings
from core.api.authentication import decode_and_validate_keycloak_token
from core.api.authentication import KeycloakClaims
from core.api.authentication import KeycloakJWTAuthentication
from core.api.authentication import KeycloakTokenUser
from core import models
from core.api.services import sample_metadata
from core.api.services import sample_metadata_ingestion
from core.api.services import schema_ingestion
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

    def test_keycloak_authorization_model_separates_project_and_lab_roles(self):
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
                        "project_role": None,
                        "labs": {"lab1": {"role": "admin"}},
                    },
                    "relecov": {
                        "project_role": None,
                        "labs": {"lab2": {"role": "view"}},
                    },
                },
            },
        )

    def test_build_user_from_token_returns_reusable_authorization_model(self):
        authorization_user = access_control.build_user_from_token(
            {
                "sub": "user-1",
                "preferred_username": "daniel",
                "groups": [
                    "/use-cases/mepram/labs/lab1/admin",
                    "/use-cases/mepram/view",
                    "/use-cases/relecov/labs/lab2/viewer",
                ],
            }
        )

        self.assertEqual(
            authorization_user.to_authorization_dict(),
            {
                "id": "user-1",
                "username": "daniel",
                "superuser": False,
                "projects": {
                    "mepram": {
                        "project_role": "view",
                        "labs": {"lab1": {"role": "admin"}},
                    },
                    "relecov": {
                        "project_role": None,
                        "labs": {"lab2": {"role": "view"}},
                    },
                },
            },
        )
        self.assertTrue(authorization_user.can("mepram"))
        self.assertFalse(authorization_user.can("mepram", role="admin"))
        self.assertTrue(authorization_user.can("mepram", lab="lab1", role="admin"))
        self.assertTrue(authorization_user.can("relecov"))
        self.assertTrue(authorization_user.can("relecov", lab="lab2"))
        self.assertFalse(authorization_user.can("relecov", lab="lab2", role="admin"))
        self.assertEqual(
            authorization_user.to_project_permissions(),
            {
                "mepram": {
                    "project_role": "view",
                    "labs": {"lab1": {"role": "admin"}},
                },
                "relecov": {
                    "project_role": None,
                    "labs": {"lab2": {"role": "view"}},
                },
            },
        )

    def test_keycloak_token_user_can_delegates_to_authorization_model(self):
        authorization_user = access_control.build_user_from_token(
            {
                "sub": "user-1",
                "preferred_username": "daniel",
                "groups": ["/use-cases/mepram/labs/lab1/admin"],
            }
        )
        user = KeycloakTokenUser(
            subject="user-1",
            username="daniel",
            authorization_model=authorization_user,
        )

        self.assertTrue(user.can("mepram"))
        self.assertTrue(user.can("mepram", lab="lab1", role="admin"))
        self.assertFalse(user.can("mepram", role="admin"))

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
        self.assertEqual(config["client_id"], "pathocore-web")


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
            {
                "mepram": {
                    "project_role": None,
                    "labs": {
                        "lab1": {
                            "role": "admin",
                        },
                    },
                },
                "relecov": {
                    "project_role": None,
                    "labs": {
                        "lab2": {
                            "role": "view",
                        },
                    },
                },
            },
        )
        self.assertEqual(response.data["token"]["preferred_username"], "juan")


@override_settings(ROOT_URLCONF="conf.urls", ALLOWED_HOSTS=["testserver", "localhost"])
class UseCaseDataSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.schema = models.Schema.objects.create(
            file_name="schemas/mepram.json",
            schema_name="MePRAM",
            schema_version="1.0",
            schema_app_name="mepram",
            schema_in_use=True,
        )
        self.sample_1 = models.Sample.objects.create(
            sample_unique_id="MEP0000001",
            sequencing_sample_id="SEQ-1",
            submitting_lab_sample_id="SUB-1",
            collecting_institution="Hospital A",
            schema_obj=self.schema,
        )
        self.sample_2 = models.Sample.objects.create(
            sample_unique_id="MEP0000002",
            sequencing_sample_id="SEQ-2",
            submitting_lab_sample_id="SUB-2",
            collecting_institution="Hospital B",
            schema_obj=self.schema,
        )
        self.properties = {
            property_name: models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property=property_name,
                type="string",
            )
            for property_name in (
                "organism",
                "sample_collection_date",
                "submitting_institution",
                "submitting_geo_loc_state",
                "collecting_institution_geo_loc_state",
                "collecting_institution_geo_loc_region",
                "specimen_source",
                "carbapenemase_genes",
                "bioinformatics_protocol_software_name",
            )
        }
        self._metadata(self.sample_1, "organism", "K. pneumoniae")
        self._metadata(self.sample_1, "sample_collection_date", "2025-01-02")
        self._metadata(self.sample_1, "submitting_institution", "Hospital A")
        self._metadata(self.sample_1, "submitting_geo_loc_state", "Comunidad de Madrid")
        self._metadata(
            self.sample_1, "collecting_institution_geo_loc_state", "Comunidad de Madrid"
        )
        self._metadata(self.sample_1, "collecting_institution_geo_loc_region", "Madrid")
        self._metadata(self.sample_1, "specimen_source", "Blood")
        self._metadata(self.sample_1, "carbapenemase_genes", "OXA-48")
        self._metadata(self.sample_1, "bioinformatics_protocol_software_name", "ivar")
        self._metadata(self.sample_2, "organism", "E. coli")
        self._metadata(self.sample_2, "sample_collection_date", "2025-02-03")
        self._metadata(self.sample_2, "submitting_institution", "Hospital B")
        self._metadata(self.sample_2, "submitting_geo_loc_state", "Cataluna")
        self._metadata(
            self.sample_2, "collecting_institution_geo_loc_region", "Barcelona"
        )
        self._metadata(self.sample_2, "specimen_source", "Urine")

    def _metadata(self, sample, property_name, value):
        return models.MetadataValues.objects.create(
            sample=sample,
            schema_property=self.properties[property_name],
            value=value,
            analysis_date=date.today(),
        )

    def test_use_case_data_summary_is_project_scoped_and_cached(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="daniel",
            groups=["/use-cases/mepram/viewer"],
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(
            "/v1/use-cases/data-summary",
            {"project_name": "mepram"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data_contract_version"], "1.2")
        self.assertEqual(payload["project_name"], "mepram")
        self.assertEqual(payload["project"], {"id": "mepram", "label": "Mepram"})
        self.assertEqual(payload["metrics"]["total_samples"], 2)
        self.assertEqual(payload["metrics"]["analyzed_samples"], 1)
        self.assertEqual(payload["metrics"]["participating_centers"], 2)
        self.assertEqual(
            payload["dimensions"]["pathogen"]["values"],
            [
                {"label": "E. coli", "value": 1},
                {"label": "K. pneumoniae", "value": 1},
            ],
        )
        self.assertEqual(
            payload["dimensions"]["pathogen"]["coverage"]["matched_samples"], 2
        )
        self.assertEqual(
            payload["dimensions"]["specimen_source"]["values"],
            [
                {"label": "Blood", "value": 1},
                {"label": "Urine", "value": 1},
            ],
        )
        self.assertIn("samples_by_month", payload["time_series"])
        self.assertIn("regions", payload["geography"])
        self.assertEqual(payload["overview"]["total_samples"], 2)
        self.assertEqual(payload["overview"]["analyzed_samples"], 1)
        self.assertEqual(payload["overview"]["participating_centers"], 2)
        self.assertEqual(
            payload["overview"]["project_pathogen_distribution"],
            [
                {"label": "E. coli", "value": 1},
                {"label": "K. pneumoniae", "value": 1},
            ],
        )
        self.assertTrue(
            models.DatabrowserSummaryCache.objects.filter(
                summary_name="use-case-data-summary",
                scope_key="project:mepram",
            ).exists()
        )

    def test_use_case_data_summary_requires_project_access(self):
        user = KeycloakTokenUser(
            subject="user-1",
            username="daniel",
            groups=["/use-cases/relecov/view"],
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(
            "/v1/use-cases/data-summary",
            {"project_name": "mepram"},
        )

        self.assertEqual(response.status_code, 403)

    def test_use_case_isolate_explorer_returns_live_rows(self):
        self.properties["amr_acquired_genes"] = models.SchemaProperties.objects.create(
            schemaID=self.schema,
            property="amr_acquired_genes",
            type="array",
        )
        self.properties["amr_acquired_genes.gene_name"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="amr_acquired_genes.gene_name",
                type="string",
            )
        )
        self.properties["amr_acquired_genes.allele_name"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="amr_acquired_genes.allele_name",
                type="string",
            )
        )
        self.properties["amr_acquired_genes.classification"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="amr_acquired_genes.classification",
                type="string",
            )
        )
        self.properties["amr_acquired_genes.origin"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="amr_acquired_genes.origin",
                type="string",
            )
        )
        self.properties["organism.species"] = models.SchemaProperties.objects.create(
            schemaID=self.schema,
            property="organism.species",
            type="string",
        )
        self.properties["organism.origin"] = models.SchemaProperties.objects.create(
            schemaID=self.schema,
            property="organism.origin",
            type="string",
        )
        self.properties["sequence_type.sequence_type_1"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="sequence_type.sequence_type_1",
                type="string",
            )
        )
        self.properties["sequence_type.sequence_type_1_scheme"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="sequence_type.sequence_type_1_scheme",
                type="string",
            )
        )
        self.properties["sequence_type.sequence_type_2_scheme"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="sequence_type.sequence_type_2_scheme",
                type="string",
            )
        )
        self.properties["sequence_type.origin"] = (
            models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property="sequence_type.origin",
                type="string",
            )
        )
        group = models.MetadataGroup.objects.create(
            sample=self.sample_1,
            group_property=self.properties["amr_acquired_genes"],
            group_index=0,
            created_at=timezone.now(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.gene_name"],
            group=group,
            value="KPC",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.allele_name"],
            group=group,
            value="blaKPC-2",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.classification"],
            group=group,
            value="Bla_Carb",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.origin"],
            group=group,
            value="isciii",
            analysis_date=date.today(),
        )
        esbl_group = models.MetadataGroup.objects.create(
            sample=self.sample_1,
            group_property=self.properties["amr_acquired_genes"],
            group_index=1,
            created_at=timezone.now(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.gene_name"],
            group=esbl_group,
            value="CTX-M",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.allele_name"],
            group=esbl_group,
            value="blaCTX-M-15",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.classification"],
            group=esbl_group,
            value="Bla_ESBL",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["amr_acquired_genes.origin"],
            group=esbl_group,
            value="submitting",
            analysis_date=date.today(),
        )
        submitting_organism_group = models.MetadataGroup.objects.create(
            sample=self.sample_1,
            group_property=self.properties["organism"],
            group_index=0,
            created_at=timezone.now(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["organism.species"],
            group=submitting_organism_group,
            value="Klebsiella pneumoniae group",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["organism.origin"],
            group=submitting_organism_group,
            value="submitting",
            analysis_date=date.today(),
        )
        isciii_organism_group = models.MetadataGroup.objects.create(
            sample=self.sample_1,
            group_property=self.properties["organism"],
            group_index=1,
            created_at=timezone.now(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["organism.species"],
            group=isciii_organism_group,
            value="K. pneumoniae",
            analysis_date=date.today(),
        )
        models.MetadataValues.objects.create(
            sample=self.sample_1,
            schema_property=self.properties["organism.origin"],
            group=isciii_organism_group,
            value="isciii",
            analysis_date=date.today(),
        )
        self._metadata(self.sample_1, "sequence_type.sequence_type_1", "307")
        self._metadata(self.sample_1, "sequence_type.sequence_type_1_scheme", "Pasteur")
        self._metadata(self.sample_1, "sequence_type.sequence_type_2_scheme", "Oxford")
        self._metadata(self.sample_1, "sequence_type.origin", "isciii")

        user = KeycloakTokenUser(
            subject="user-1",
            username="daniel",
            groups=["/use-cases/mepram/viewer"],
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(
            "/v1/use-cases/isolate-explorer",
            {"project_name": "mepram"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data_contract_version"], "1.2")
        self.assertEqual(payload["project_name"], "mepram")
        self.assertEqual(payload["total_samples"], 2)
        self.assertEqual(payload["matched_samples"], 2)
        self.assertEqual(payload["total_loaded"], 2)
        row = next(
            item for item in payload["rows"] if item["sample_unique_id"] == "MEP0000001"
        )
        self.assertEqual(row["sample_unique_id"], "MEP0000001")
        self.assertEqual(row["sequencing_sample_id"], "SEQ-1")
        self.assertEqual(row["collection_date"], "2025-01-02")
        self.assertEqual(row["pathogen"], "K. pneumoniae")
        self.assertEqual(row["species"], "K. pneumoniae")
        self.assertEqual(row["species_group"], "Klebsiella pneumoniae group")
        self.assertEqual(row["province"], "Madrid")
        self.assertEqual(row["is_sequenced"], True)
        self.assertEqual(row["sequencing_status"], "Sequenced")
        self.assertEqual(row["data_origin"], "isciii")
        self.assertEqual(row["sequence_type"], "ST307")
        self.assertEqual(row["sequence_type_schemes"], ["Pasteur", "Oxford"])
        self.assertEqual(row["amr_gene"], "CTX-M, KPC")
        self.assertEqual(row["amr_allele"], "blaCTX-M-15, blaKPC-2")
        self.assertEqual(row["amr_classification"], "Bla_Carb, Bla_ESBL")
        self.assertEqual(row["bla_carb"], "KPC > blaKPC-2")
        self.assertEqual(row["bla_esbl"], "CTX-M > blaCTX-M-15")
        self.assertEqual(row["amr_gene_records"][0]["gene"], "CTX-M")
        submitting_row = next(
            item for item in payload["rows"] if item["sample_unique_id"] == "MEP0000002"
        )
        self.assertIsNone(submitting_row["species"])
        self.assertEqual(submitting_row["species_group"], "E. coli")
        self.assertEqual(submitting_row["is_sequenced"], False)
        self.assertEqual(submitting_row["sequencing_status"], "Not sequenced")
        self.assertNotIn("carbapenemase", row)
        self.assertNotIn("sequencing_platform", row)
        self.assertNotIn("resistance_profile", row)
        self.assertNotIn("resistance_profiles", payload["filter_options"])
        self.assertNotIn("sequencing_platforms", payload["filter_options"])
        self.assertEqual(payload["filter_options"]["genes"], ["CTX-M", "KPC"])
        self.assertEqual(
            payload["filter_options"]["alleles"],
            ["blaCTX-M-15", "blaKPC-2"],
        )
        self.assertEqual(
            payload["filter_options"]["classifications"],
            ["Bla_Carb", "Bla_ESBL"],
        )
        self.assertEqual(
            payload["filter_options"]["bla_groups"],
            ["bla_carb", "bla_esbl"],
        )
        self.assertIn("Madrid", payload["filter_options"]["provinces"])
        self.assertIn(
            "K. pneumoniae",
            payload["filter_options"]["pathogens"],
        )
        self.assertEqual(
            payload["data_quality"]["fields"]["bla_carb"]["matched_samples"],
            1,
        )
        filtered_response = self.client.get(
            "/v1/use-cases/isolate-explorer",
            {"project_name": "mepram", "province": "Madrid"},
        )
        self.assertEqual(filtered_response.status_code, 200)
        filtered_payload = filtered_response.json()
        self.assertEqual(filtered_payload["matched_samples"], 1)
        self.assertEqual(
            filtered_payload["rows"][0]["sample_unique_id"],
            "MEP0000001",
        )
        gene_combo_response = self.client.get(
            "/v1/use-cases/isolate-explorer",
            {"project_name": "mepram", "gene": "KPC,CTX-M"},
        )
        self.assertEqual(gene_combo_response.status_code, 200)
        self.assertEqual(gene_combo_response.json()["matched_samples"], 1)
        bla_combo_response = self.client.get(
            "/v1/use-cases/isolate-explorer",
            {"project_name": "mepram", "bla_group": "bla_carb,bla_esbl"},
        )
        self.assertEqual(bla_combo_response.status_code, 200)
        self.assertEqual(bla_combo_response.json()["matched_samples"], 1)
        tokenized_search_response = self.client.get(
            "/v1/use-cases/isolate-explorer",
            {"project_name": "mepram", "search": "KPC CTX-M"},
        )
        self.assertEqual(tokenized_search_response.status_code, 200)
        self.assertEqual(tokenized_search_response.json()["matched_samples"], 1)


class ComplexMetadataTests(TestCase):
    def setUp(self):
        self.schema = models.Schema.objects.create(
            file_name="schemas/mepram.json",
            schema_name="MePRAM",
            schema_version="1.0",
            schema_app_name="mepram",
            schema_in_use=True,
        )
        self.properties = {}
        for property_name in (
            "bioinformatics_analysis_date",
            "amr_acquired_genes",
            "amr_acquired_genes.gene_name",
            "amr_acquired_genes.origin",
            "organism",
            "organism.species",
            "organism.origin",
        ):
            property_type = (
                "array"
                if property_name in {"amr_acquired_genes", "organism"}
                else "string"
            )
            self.properties[property_name] = models.SchemaProperties.objects.create(
                schemaID=self.schema,
                property=property_name,
                type=property_type,
            )
        self.sample_1 = models.Sample.objects.create(
            sample_unique_id="MEP0000001",
            sequencing_sample_id="SEQ-1",
            submitting_lab_sample_id="SUB-1",
            collecting_institution="Hospital A",
            schema_obj=self.schema,
        )
        self.sample_2 = models.Sample.objects.create(
            sample_unique_id="MEP0000002",
            sequencing_sample_id="SEQ-2",
            submitting_lab_sample_id="SUB-2",
            collecting_institution="Hospital B",
            schema_obj=self.schema,
        )

    def _ingest_metadata(self, sample, amr_records, organism_origin="isciii"):
        create_specs = sample_metadata_ingestion.prepare_sample_metadata_create(
            sample,
            self.schema,
            {
                "bioinformatics_analysis_date": "2026-01-10",
                "amr_acquired_genes": amr_records,
                "organism": [
                    {
                        "species": "Escherichia coli",
                        "origin": organism_origin,
                    }
                ],
            },
        )
        sample_metadata_ingestion.create_sample_metadata_values(create_specs)

    def test_complex_metadata_ingestion_creates_groups_and_dotted_values(self):
        self._ingest_metadata(
            self.sample_1,
            [
                {"gene_name": "VIM", "origin": "isciii"},
                {"gene_name": "NDM", "origin": "submitting"},
            ],
        )

        self.assertEqual(
            models.MetadataGroup.objects.filter(
                sample=self.sample_1,
                group_property=self.properties["amr_acquired_genes"],
            ).count(),
            2,
        )
        grouped_metadata = sample_metadata.list_sample_metadata(self.sample_1)

        self.assertIn(
            {
                "property": "amr_acquired_genes.origin",
                "value": "isciii",
                "classification": None,
                "group_id": models.MetadataGroup.objects.get(
                    sample=self.sample_1,
                    group_property=self.properties["amr_acquired_genes"],
                    group_index=0,
                ).id,
                "group_index": 0,
                "group_property": "amr_acquired_genes",
            },
            grouped_metadata,
        )

    def test_complex_metadata_search_requires_same_group_for_child_filters(self):
        self._ingest_metadata(
            self.sample_1,
            [
                {"gene_name": "VIM", "origin": "isciii"},
                {"gene_name": "NDM", "origin": "submitting"},
            ],
        )
        self._ingest_metadata(
            self.sample_2,
            [{"gene_name": "VIM", "origin": "submitting"}],
            organism_origin="submitting",
        )

        results = sample_metadata.search_samples_metadata(
            [
                {"property": "amr_acquired_genes.gene_name", "value": "VIM"},
                {"property": "amr_acquired_genes.origin", "value": "submitting"},
            ],
            match="all",
        )

        self.assertEqual(
            [item["sample_unique_id"] for item in results],
            ["MEP0000002"],
        )

    def test_complex_metadata_can_be_searched_by_single_child_property(self):
        self._ingest_metadata(
            self.sample_1,
            [{"gene_name": "VIM", "origin": "isciii"}],
        )

        results = sample_metadata.list_samples_by_metadata_query(
            property_name="organism.origin",
            values=["isciii"],
            match="any",
        )

        self.assertEqual(
            results,
            [
                {
                    "sample_unique_id": "MEP0000001",
                    "values": {"organism.origin": "isciii"},
                }
            ],
        )

    def test_schema_ingestion_registers_nested_child_properties(self):
        user = User.objects.create_superuser(
            username="admin",
            email="admin@example.test",
            password="password",
        )

        schema_create_data = schema_ingestion.prepare_schema_create(
            {
                "schema": {
                    "title": "Nested MePRAM",
                    "version": "1.0",
                    "type": "object",
                    "properties": {
                        "organism": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "species": {
                                        "type": "string",
                                        "classification": "Strain characterization",
                                    },
                                    "origin": {
                                        "type": "string",
                                        "enum": ["submitting", "isciii"],
                                        "classification": (
                                            "Sample collecting and processing"
                                        ),
                                    },
                                },
                            },
                            "required": ["species", "origin"],
                        }
                    },
                },
                "schema_app_name": "mepram",
            },
            request_user=user,
        )

        property_specs = {
            item["property"]: item for item in schema_create_data["property_specs"]
        }
        self.assertIn("organism", property_specs)
        self.assertIn("organism.species", property_specs)
        self.assertIn("organism.origin", property_specs)
        self.assertTrue(property_specs["organism.origin"]["options"])
        self.assertEqual(
            property_specs["organism.origin"]["enum_values"],
            ["submitting", "isciii"],
        )


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


@override_settings(ROOT_URLCONF="conf.urls", ALLOWED_HOSTS=["testserver", "localhost"])
class DocumentationAuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_openapi_is_public(self):
        response = self.client.get("/v1/openapi/")

        self.assertEqual(response.status_code, 200)

    def test_swagger_is_public(self):
        response = self.client.get("/v1/swagger/")
        self.assertEqual(response.status_code, 200)

    def test_redoc_is_public(self):
        response = self.client.get("/v1/swagger/redoc/")

        self.assertEqual(response.status_code, 200)

    def test_use_case_endpoints_still_require_authentication(self):
        response = self.client.get(
            "/v1/use-cases/data-summary",
            {"project_name": "mepram"},
        )

        self.assertIn(response.status_code, (401, 403))

    def test_legacy_openapi_redirects_to_v1(self):
        response = self.client.get("/openapi/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/v1/openapi/")

    def test_legacy_swagger_redirects_to_v1(self):
        response = self.client.get("/swagger/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/v1/swagger/")


@override_settings(
    ROOT_URLCONF="conf.urls",
    ALLOWED_HOSTS=["testserver", "localhost"],
    PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS=False,
)
class PublicReadEndpointSettingsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_public_read_endpoints_can_be_disabled(self):
        response = self.client.get("/v1/databrowser/overview-summary")

        self.assertEqual(response.status_code, 403)


@override_settings(
    ROOT_URLCONF="conf.urls",
    ALLOWED_HOSTS=["testserver", "localhost"],
    PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS=True,
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "anon": "2/minute",
            "user": "2/minute",
        },
    },
)
class DRFRateThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    @patch("core.api.v1.views.databrowser.overview_summary")
    def test_public_endpoint_works_below_rate_limit_without_authentication(
        self, overview_summary
    ):
        overview_summary.return_value = self._overview_payload()

        response = self.client.get("/v1/databrowser/overview-summary")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HTTP_AUTHORIZATION", response.wsgi_request.META)

    @patch("core.api.v1.views.databrowser.overview_summary")
    def test_public_endpoint_returns_429_after_rate_limit(self, overview_summary):
        overview_summary.return_value = self._overview_payload()

        first = self.client.get("/v1/databrowser/overview-summary")
        second = self.client.get("/v1/databrowser/overview-summary")
        third = self.client.get("/v1/databrowser/overview-summary")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)
        self.assertIn("detail", third.data)
        self.assertIn("Request was throttled.", str(third.data["detail"]))

    @patch("core.api.v1.views.databrowser.overview_summary")
    def test_public_throttle_is_scoped_by_client_ip(self, overview_summary):
        overview_summary.return_value = self._overview_payload()

        self.client.get("/v1/databrowser/overview-summary", REMOTE_ADDR="10.0.0.1")
        self.client.get("/v1/databrowser/overview-summary", REMOTE_ADDR="10.0.0.1")
        limited_response = self.client.get(
            "/v1/databrowser/overview-summary",
            REMOTE_ADDR="10.0.0.1",
        )
        other_ip_response = self.client.get(
            "/v1/databrowser/overview-summary",
            REMOTE_ADDR="10.0.0.2",
        )

        self.assertEqual(limited_response.status_code, 429)
        self.assertEqual(other_ip_response.status_code, 200)

    @patch("core.api.v1.views.databrowser.overview_summary")
    def test_public_endpoint_does_not_require_authorization_header(
        self, overview_summary
    ):
        overview_summary.return_value = self._overview_payload()

        response = self.client.get("/v1/databrowser/overview-summary")

        self.assertEqual(response.status_code, 200)

    @patch("core.api.v1.views.databrowser.overview_summary")
    def test_private_auth_endpoint_still_uses_authentication_flow(
        self, overview_summary
    ):
        overview_summary.return_value = self._overview_payload()

        auth_response = self.client.get("/v1/auth/me")

        self.assertIn(auth_response.status_code, (401, 403))

    @staticmethod
    def _overview_payload():
        return {
            "kpis": [],
            "sample_growth": [],
            "pathogens": [],
            "geography": [],
            "schema_mix": [],
            "projects": [],
            "notes": [],
            "coverage_notes": [],
            "metrics": {},
        }


class DefaultSuperuserCommandTests(TestCase):
    def test_command_creates_or_updates_default_superuser(self):
        call_command(
            "ensure_default_superuser",
            username="admin",
            email="admin@example.org",
            password="admin_pass",
        )

        user = User.objects.get(username="admin")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("admin_pass"))

        call_command(
            "ensure_default_superuser",
            username="admin",
            email="admin@example.org",
            password="new_pass",
        )

        user.refresh_from_db()
        self.assertTrue(user.check_password("new_pass"))


@override_settings(
    ROOT_URLCONF="conf.urls",
    ALLOWED_HOSTS=["testserver", "localhost"],
    PATHOCORE_ACCESS_REQUEST_USE_CASES=[
        {"name": "mepram", "label": "MEPRAM", "labs": []},
        {"name": "redlabra", "label": "RedLaBRA", "labs": []},
    ],
    PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS=[],
)
class AccessRequestWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.org",
            password="admin-pass",
        )

    def test_public_user_can_create_pending_access_request(self):
        response = self.client.post(
            "/api/v1/access-requests",
            data=self._request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["requested_use_case"], "mepram")
        self.assertIsNone(response.data["requested_lab"])
        self.assertEqual(models.AccessRequest.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new.user@example.org"])
        self.assertEqual(
            mail.outbox[0].subject,
            f"[PathoCore access #{response.data['id']}] MEPRAM (view) - new_user",
        )
        self.assertEqual(
            mail.outbox[0].extra_headers["Message-ID"],
            (
                f"<pathocore-access-request-{response.data['id']}-received"
                "@localhost>"
            ),
        )

    def test_legacy_v1_alias_still_accepts_access_request(self):
        response = self.client.post(
            "/v1/access-requests",
            data=self._request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(models.AccessRequest.objects.count(), 1)

    def test_public_user_can_create_multiple_pending_access_requests(self):
        payload = {
            "username": "new_user",
            "email": "new.user@example.org",
            "first_name": "New",
            "last_name": "User",
            "message": "I collaborate with MEPRAM and RedLaBRA.",
            "requests": [
                {"use_case": "mepram", "role": "view"},
                {"use_case": "redlabra", "role": "admin"},
            ],
        }

        response = self.client.post(
            "/api/v1/access-requests",
            data=payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(models.AccessRequest.objects.count(), 2)
        self.assertEqual(
            [item["requested_use_case"] for item in response.data],
            ["mepram", "redlabra"],
        )
        self.assertEqual(
            [item["requested_role"] for item in response.data],
            ["view", "admin"],
        )
        self.assertEqual(len(mail.outbox), 2)

    def test_multiple_access_request_rejects_duplicate_scope_entries(self):
        payload = {
            "username": "new_user",
            "email": "new.user@example.org",
            "first_name": "New",
            "last_name": "User",
            "requests": [
                {"use_case": "mepram", "role": "view"},
                {"use_case": "mepram", "role": "viewer"},
            ],
        }

        response = self.client.post(
            "/api/v1/access-requests",
            data=payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(models.AccessRequest.objects.count(), 0)

    @patch("core.api.services.keycloak_admin.list_group_member_emails")
    def test_access_request_notifies_keycloak_use_case_admins(self, emails_mock):
        emails_mock.return_value = [
            "mepram.admin@example.org",
            "mepram.admin@example.org",
            "other.admin@example.org",
        ]

        response = self.client.post(
            "/v1/access-requests",
            data=self._request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        emails_mock.assert_called_once_with("/use-cases/mepram/admin")
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Technical platforms:", mail.outbox[0].body)
        self.assertIn("https://github.com/BIPLAT-CIBERINFEC/", mail.outbox[0].body)
        self.assertEqual(
            mail.outbox[1].to,
            ["mepram.admin@example.org", "other.admin@example.org"],
        )
        self.assertEqual(mail.outbox[1].subject, mail.outbox[0].subject)
        self.assertEqual(
            mail.outbox[1].extra_headers["In-Reply-To"],
            mail.outbox[0].extra_headers["Message-ID"],
        )
        self.assertEqual(
            mail.outbox[1].extra_headers["References"],
            mail.outbox[0].extra_headers["Message-ID"],
        )
        self.assertIn("https://github.com/BU-ISCIII", mail.outbox[1].body)

    @override_settings(PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS=["fallback@example.org"])
    @patch("core.api.services.keycloak_admin.list_group_member_emails")
    def test_access_request_uses_fallback_admin_email_when_keycloak_fails(
        self, emails_mock
    ):
        from core.api.services import keycloak_admin

        emails_mock.side_effect = keycloak_admin.KeycloakAdminError("unavailable")

        response = self.client.post(
            "/v1/access-requests",
            data=self._request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["fallback@example.org"])

    @override_settings(DEFAULT_FROM_EMAIL="bioinformatica.infec@ciberisciii.es")
    def test_access_request_email_thread_uses_sender_domain(self):
        response = self.client.post(
            "/v1/access-requests",
            data=self._request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            mail.outbox[0].extra_headers["Message-ID"],
            (
                f"<pathocore-access-request-{response.data['id']}-received"
                "@ciberisciii.es>"
            ),
        )

    def test_admin_can_list_pending_access_requests(self):
        models.AccessRequest.objects.create(**self._request_payload())

        anonymous_response = self.client.get("/v1/access-requests?status=pending")
        self.assertIn(anonymous_response.status_code, (401, 403))

        response = self.client.get(
            "/v1/access-requests?status=pending",
            HTTP_AUTHORIZATION=self._basic_auth("admin", "admin-pass"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["status"], "pending")

    @patch("core.api.services.keycloak_admin.provision_approved_user")
    def test_admin_can_approve_access_request(self, provision_mock):
        access_request = models.AccessRequest.objects.create(**self._request_payload())
        provision_mock.return_value = {
            "user_id": "keycloak-user-1",
            "group_id": "group-1",
            "group_path": "/use-cases/mepram/view",
        }

        response = self.client.post(
            f"/v1/access-requests/{access_request.pk}/approve",
            data={"review_note": "Approved"},
            format="json",
            HTTP_AUTHORIZATION=self._basic_auth("admin", "admin-pass"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "approved")
        self.assertEqual(
            response.data["approved_group"],
            "/use-cases/mepram/view",
        )
        self.assertEqual(response.data["keycloak_user_id"], "keycloak-user-1")
        provision_mock.assert_called_once()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].subject,
            f"[PathoCore access #{access_request.pk}] MEPRAM (view) - new_user",
        )
        self.assertEqual(
            mail.outbox[0].extra_headers["In-Reply-To"],
            (
                f"<pathocore-access-request-{access_request.pk}-received"
                "@localhost>"
            ),
        )
        self.assertIn("MEPRAM (view)", mail.outbox[0].body)
        self.assertIn(
            "https://mepram-datahub.ciberisciii.es/use-cases/mepram",
            mail.outbox[0].body,
        )
        self.assertIn("Technical platforms:", mail.outbox[0].body)

    @patch("core.api.services.keycloak_admin.list_group_member_emails")
    def test_admin_can_reject_access_request(self, emails_mock):
        emails_mock.return_value = ["mepram.admin@example.org"]
        access_request = models.AccessRequest.objects.create(**self._request_payload())

        response = self.client.post(
            f"/v1/access-requests/{access_request.pk}/reject",
            data={"review_note": "Missing project justification"},
            format="json",
            HTTP_AUTHORIZATION=self._basic_auth("admin", "admin-pass"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "rejected")
        self.assertEqual(
            response.data["review_note"],
            "Missing project justification",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new.user@example.org"])
        self.assertEqual(
            mail.outbox[0].subject,
            f"[PathoCore access #{access_request.pk}] MEPRAM (view) - new_user",
        )
        self.assertEqual(
            mail.outbox[0].extra_headers["In-Reply-To"],
            (
                f"<pathocore-access-request-{access_request.pk}-received"
                "@localhost>"
            ),
        )
        self.assertIn("Reason: Missing project justification", mail.outbox[0].body)
        self.assertIn("contact: mepram.admin@example.org", mail.outbox[0].body)
        self.assertIn("Technical platforms:", mail.outbox[0].body)

    @patch("core.api.services.keycloak_admin.revoke_approved_user_access")
    @patch("core.api.services.keycloak_admin.list_group_member_emails")
    def test_admin_can_revoke_approved_access_request(self, emails_mock, revoke_mock):
        emails_mock.return_value = ["mepram.admin@example.org"]
        access_request = models.AccessRequest.objects.create(
            **self._request_payload(),
            status=models.AccessRequest.STATUS_APPROVED,
            approved_group="/use-cases/mepram/view",
            keycloak_user_id="keycloak-user-1",
        )
        revoke_mock.return_value = {
            "user_id": "keycloak-user-1",
            "group_id": "group-1",
            "group_path": "/use-cases/mepram/view",
        }

        response = self.client.post(
            f"/v1/access-requests/{access_request.pk}/revoke",
            data={"review_note": "Access no longer required"},
            format="json",
            HTTP_AUTHORIZATION=self._basic_auth("admin", "admin-pass"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "revoked")
        self.assertEqual(response.data["approved_group"], "/use-cases/mepram/view")
        revoke_mock.assert_called_once()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new.user@example.org"])
        self.assertEqual(
            mail.outbox[0].subject,
            f"[PathoCore access #{access_request.pk}] MEPRAM (view) - new_user",
        )
        self.assertEqual(
            mail.outbox[0].extra_headers["In-Reply-To"],
            (
                f"<pathocore-access-request-{access_request.pk}-received"
                "@localhost>"
            ),
        )
        self.assertIn("Reason: Access no longer required", mail.outbox[0].body)
        self.assertIn("contact: mepram.admin@example.org", mail.outbox[0].body)
        self.assertIn("Technical platforms:", mail.outbox[0].body)

    @staticmethod
    def _request_payload():
        return {
            "username": "new_user",
            "email": "new.user@example.org",
            "first_name": "New",
            "last_name": "User",
            "requested_use_case": "mepram",
            "requested_role": "view",
            "message": "I collaborate with the MEPRAM laboratory network.",
        }

    @staticmethod
    def _basic_auth(username, password):
        raw_credentials = f"{username}:{password}".encode("utf-8")
        encoded = base64.b64encode(raw_credentials).decode("ascii")
        return f"Basic {encoded}"
