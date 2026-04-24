# Test Data Generation for Volunteer System

This directory contains scripts to generate test data for the volunteer system, including users with different roles and test projects.

## Overview

The volunteer system has three user roles:
- **Volunteer**: Regular volunteers who can apply to projects
- **Organiser**: Users who can create and manage projects
- **Admin**: Super users with full access to all features

## Scripts

### 1. Django Management Commands (Recommended)

These commands are integrated into the Django project and provide the most reliable way to create test data.

#### Create Test Users

```bash
cd /home/ruslan/Desktop/Diploma/Diploma_web/volunteer

# Create 5 users per role (volunteer, organiser, admin)
python manage.py create_test_users

# Create 10 users per role
python manage.py create_test_users --count 10

# Create only volunteers and organisers
python manage.py create_test_users --roles volunteer,organiser --count 5

# Clear existing test users and create new ones
python manage.py create_test_users --clear --count 20
```

**Default Password:** `test123456`

**User Naming Convention:**
- Volunteers: `test_volunteer_1`, `test_volunteer_2`, ...
- Organisers: `test_organiser_1`, `test_organiser_2`, ...
- Admins: `test_admin_1`, `test_admin_2`, ...

#### Create Test Projects

```bash
# Create 10 test projects
python manage.py create_test_projects

# Create 15 test projects
python manage.py create_test_projects --count 15

# Create projects with volunteer assignments
python manage.py create_test_projects --count 10 --min-volunteers 2 --max-volunteers 5

# Clear existing test projects and create new ones
python manage.py create_test_projects --clear --count 20
```

**Features:**
- Projects are assigned to random organisers
- Random locations, descriptions, and dates
- Optional volunteer assignments with random statuses
- Configurable volunteer limits per project

#### Combined Workflow

```bash
# Create users and projects together
python manage.py create_test_users --count 10 --clear
python manage.py create_test_projects --count 15 --min-volunteers 1 --max-volunteers 3
```

### 2. Standalone Python Script

The standalone script (`create_test_data.py`) can be run directly without Django management commands.

```bash
cd /home/ruslan/Desktop/Diploma/Diploma_web

# Create users and projects
python create_test_data.py --count 10 --clear

# Create only projects
python create_test_data.py --create-projects-only --count 15

# Custom password and roles
python create_test_data.py --count 5 --roles volunteer,organiser --password mypassword
```

**Arguments:**
- `--count`: Number of users per role (default: 5)
- `--roles`: Comma-separated roles (default: volunteer,organiser,admin)
- `--clear`: Delete existing test data first
- `--password`: Password for created users (default: test123456)
- `--create-projects-only`: Skip user creation
- `--min-volunteers`: Minimum volunteers per project
- `--max-volunteers`: Maximum volunteers per project
- `--project-count`: Number of projects to create

### 3. Flutter/Dart Script

The Dart script (`create_test_users.dart`) can be used for testing the Flutter app's API integration.

```bash
cd /home/ruslan/Desktop/Diploma/Diploma_phone/volunteer

# Run the script
dart run test/create_test_users.dart

# With custom parameters
dart run test/create_test_users.dart --count 10 --roles volunteer,organiser --url http://localhost:8000
```

**Note:** This script primarily tests API connectivity and project creation. For creating users with specific roles, use the Python scripts which have direct database access.

## API Testing

After creating test users, you can test the API:

### Login as Volunteer
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test_volunteer_1@volunteer.test", "password": "test123456"}'
```

### Login as Organiser
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test_organiser_1@volunteer.test", "password": "test123456"}'
```

### Get All Users (Admin only)
```bash
curl -X GET http://localhost:8000/api/users/ \
  -H "Authorization: Token <your_token>"
```

### Get All Projects
```bash
curl -X GET http://localhost:8000/api/projects/
```

### Apply to Project
```bash
curl -X POST http://localhost:8000/api/projects/1/apply/ \
  -H "Authorization: Token <your_token>"
```

### Create Project (Organiser/Admin)
```bash
curl -X POST http://localhost:8000/api/projects/ \
  -H "Authorization: Token <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Project",
    "description": "Test description",
    "location": "Test location",
    "hours": 5,
    "max_volunteers": 10,
    "days": 7
  }'
```

## Database Models

### UserProfile
- **role**: `volunteer` | `organiser` | `admin`
- **group_name**: e.g., `IT-21`, `IT-32` (for volunteers)

### Project
- **organiser**: ForeignKey to User
- **name**: Project name
- **description**: Project description
- **location**: Project location
- **date**: Project date
- **hours**: Volunteer hours for completion
- **max_volunteers**: Maximum volunteers (0 = unlimited)
- **current_volunteers**: Current volunteer count
- **status**: `apply` | `pending` | `approved` | `rejected`

### Request (Volunteer Application)
- **Volunteer**: ForeignKey to User
- **event**: ForeignKey to Project
- **status**: `pending` | `approved` | `completed` | `rejected`
- **approved_hours**: Hours approved by organiser
- **organizer_report**: Report from organiser
- **star_rating**: Boolean rating

## Examples

### Development Workflow
```bash
# 1. Start Django server
cd /home/ruslan/Desktop/Diploma/Diploma_web/volunteer
python manage.py runserver

# 2. In another terminal, create test data
cd /home/ruslan/Desktop/Diploma/Diploma_web/volunteer
python manage.py create_test_users --count 10 --clear
python manage.py create_test_projects --count 15 --min-volunteers 2

# 3. Start Flutter app
cd /home/ruslan/Desktop/Diploma/Diploma_phone/volunteer
flutter run
```

### Testing Different Roles
```bash
# Create specific role combinations
python manage.py create_test_users --roles volunteer --count 20
python manage.py create_test_users --roles organiser --count 5
python manage.py create_test_users --roles admin --count 2

# Create mixed roles
python manage.py create_test_users --count 5  # All roles
```

### Bulk Project Creation
```bash
# Create many projects with volunteer assignments
python manage.py create_test_projects \
  --count 50 \
  --min-volunteers 3 \
  --max-volunteers 10
```

## Troubleshooting

### Django Command Not Found
Make sure you're in the Django project directory:
```bash
cd /home/ruslan/Desktop/Diploma/Diploma_web/volunteer
```

### Database Not Initialized
Run migrations first:
```bash
cd /home/ruslan/Desktop/Diploma/Diploma_web/volunteer
python manage.py migrate
```

### Server Not Running
The Django server must be running to test API endpoints:
```bash
python manage.py runserver
```

### Permission Errors
Only admins and organisers can create projects via the API. Make sure to:
1. Create an admin user first
2. Login as admin to get a token
3. Use the token in API requests

## Notes

- All created test users have the same password (configurable)
- Email addresses use the `@volunteer.test` domain for easy identification
- Test data can be safely deleted and recreated
- The scripts are idempotent - running them multiple times is safe
- User creation respects existing users (won't overwrite)
