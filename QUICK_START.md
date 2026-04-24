# Test Data Quick Start Guide

## One-Line Commands

### Create All Test Users (6 users, 2 per role)
```bash
cd /home/ruslan/Desktop/Diploma/Diploma_web/volunteer
source ../venv/bin/activate
python manage.py create_test_users --clear --count 2
```

### Create All Test Users (10 users per role = 30 total)
```bash
python manage.py create_test_users --clear --count 10
```

### Create Test Projects
```bash
python manage.py create_test_projects --count 10 --min-volunteers 2
```

### Create Everything (10 users per role + 15 projects)
```bash
python manage.py create_test_users --clear --count 10 && python manage.py create_test_projects --count 15 --min-volunteers 2
```

## Available Roles

- `volunteer` - Regular volunteers
- `organiser` - Project organizers
- `admin` - Administrators

## Login Credentials

**Username Format:** `test_{role}_{number}`  
**Email Format:** `test_{role}_{number}@volunteer.test`  
**Password:** `test123456`

### Examples

| Role | Username | Email |
|------|----------|-------|
| Volunteer | test_volunteer_1 | test_volunteer_1@volunteer.test |
| Organiser | test_organiser_1 | test_organiser_1@volunteer.test |
| Admin | test_admin_1 | test_admin_1@volunteer.test |

## API Login Example

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test_volunteer_1@volunteer.test", "password": "test123456"}'
```

## Cleanup

```bash
# Remove all test users only
python manage.py create_test_users --clear --count 0

# Remove all test data and recreate
python manage.py create_test_users --clear --count 10
python manage.py create_test_projects --clear --count 10
```

## Flutter Testing

```bash
cd /home/ruslan/Desktop/Diploma/Diploma_phone/volunteer
dart run test/create_test_users.dart --count 5
```

## Standalone Script

```bash
cd /home/ruslan/Desktop/Diploma/Diploma_web
source venv/bin/activate
python create_test_data.py --count 10 --clear
```

## Full Documentation

See [README_TEST_DATA.md](README_TEST_DATA.md) for complete documentation.
