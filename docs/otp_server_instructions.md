<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# OTP Code Generation Instructions for the University Server

This document explains how the university server should generate a 6-digit OTP token from the 6-digit `setup_code` shown by the app.

## Purpose

- The mobile app shows the user a 6-digit `setup_code`.
- The user enters that code on the university server.
- The server returns a 6-digit `otp_token`.
- The backend then verifies that token when it confirms a sensitive action.

## Input

- One value: `setup_code`
- It must contain exactly 6 digits, for example `123456`

## Output

- One value: `otp_token`
- It must contain exactly 6 digits, with leading zeroes if necessary

## Algorithm

The server must use a secret key that is known only to it and to the backend.

Do the following:

```text
digest = HMAC-SHA256(secret, setup_code)
otp_token = int(first 12 hexadecimal characters of digest, base 16) mod 1_000_000
otp_token = formatted as a 6-digit string
```

## Pseudocode

```pseudo
function generateOtpToken(setupCode, secret):
    setupCode = trim(setupCode)

    if setupCode does not match /^[0-9]{6}$/:
        reject the input with an error

    digest = HMAC_SHA256(secret, setupCode)
    hexPart = first 12 hexadecimal characters of digest
    number = parseHex(hexPart)
    token = number mod 1000000

    return token as a 6-digit string
```

## Validation Rules

- Accept only exactly 6 digits.
- Reject everything else.
- Do not log the secret key.
- Do not log the generated OTP token unless it is necessary for debugging in a secure environment.

## Security Notes

- The secret key must stay only on the server side.
- The token must be short-lived.
- The token must be bound to the specific `setup_code` and must not be reused for other actions.

## Compatibility

This algorithm must match the backend verification logic.
If the generation algorithm changes on the server, the backend must be updated as well.
