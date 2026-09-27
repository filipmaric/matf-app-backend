<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# Production

Production uses `systemd` and Gunicorn.

The service should:

- run from `/var/www/matf-app`
- load `/var/www/matf-app/matf.env` through `EnvironmentFile=`
- start `gunicorn -b 127.0.0.1:5000 wsgi:application`

Required environment variables are listed in `README.md` and in `deploy/matf.env.example`.

For a CI-friendly docs check, run:

```bash
mkdocs build --strict
```

## Review Deployment

For Play Console review, keep the backend review instance separate from production and
point it at a public mock Hypatia service.

Suggested layout:

- backend review service using `deploy/review.env.example`
- public mock Hypatia service using `mock_hypatia_server/deploy/mock_hypatia.service.example`

The review backend should use:

- `REVIEW_MODE=1`
- `GRADES_SOURCE_URL=https://<review-mock>/api/grades`
- `HYPATIA_EXAM_APPLICATIONS_URL=https://<review-mock>/api/exam-applications`
- `HYPATIA_LINK_URL=https://<review-mock>/mock/exam-link-server`

The mock Hypatia service should use the same shared secrets as the review backend.
