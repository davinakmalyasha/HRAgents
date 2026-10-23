# API reference

The API is a FastAPI application. Every instance serves its own OpenAPI 3.1
document at `/openapi.json`, interactive Swagger at `/docs` and ReDoc at
`/redoc`. The specification below is the one committed with this release.

Authentication is an `X-API-Key` header. Permissions are checked per route and
return a `403` with a stable problem `code` when the role is not entitled; a
missing or refused credential is a `401` that names which of the two it was.
Errors are `application/problem+json` with a stable `code` (see
[Deployment & operations](deployment.md)).

<swagger-ui src="api/openapi.json"/>
