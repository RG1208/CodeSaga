# Support desk architecture

The service is a small FastAPI application with a React front end.

## Authentication

Agents sign in with an email and a password. Passwords are stored as salted PBKDF2
hashes and never in plain text. A successful sign-in returns a signed bearer token.

## Billing

Charges and refunds go through a single payment gateway wrapper. Refunds may be
partial, and an uncaptured authorisation is voided rather than refunded.

## Throttling

Every client gets a token bucket. When the bucket is empty the API answers 429 and
tells the caller how long to wait.

## Caching

Hot lookups are cached in memory with a least-recently-used policy.
