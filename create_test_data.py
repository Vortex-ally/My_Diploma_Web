#!/usr/bin/env python3
"""
Standalone script to create test users and projects for the volunteer system.

This script can be run directly to populate the database with test data.
It creates users with different roles (volunteer, organiser, admin) and
test projects with various configurations.

Usage:
    python create_test_data.py [options]

Examples:
    # Create 10 users per role
    python create_test_data.py --count 10

    # Create only volunteers and organisers
    python create_test_data.py --roles volunteer,organiser --count 5

    # Clear existing data and create new
    python create_test_data.py --clear --count 20

    # Create projects only
    python create_test_data.py --create-projects-only --count 15
"""

import os
import sys
import argparse
import random
from datetime import datetime, timedelta

# Add the Django project to the path
DJANGO_DIR = os.path.dirname(os.path.abspath(__file__))
VOLUNTEER_DIR = os.path.join(DJANGO_DIR, "volunteer")
sys.path.insert(0, VOLUNTEER_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "volunteer.settings")

import django

django.setup()

from django.contrib.auth.models import User
from volunteer_app.models import UserProfile, Project, Request, GroupTemplate


def create_test_users(count=5, roles=None, clear=False, password="test123456"):
    """
    Create test users with specified roles.

    Args:
        count: Number of users to create per role
        roles: List of roles to create (volunteer, organiser, admin)
        clear: Whether to delete existing test users first
        password: Password for all created users

    Returns:
        List of created users
    """
    if roles is None:
        roles = ["volunteer", "organiser", "admin"]

    created_users = []

    if clear:
        print("Deleting existing test users...")
        for role in ["volunteer", "organiser", "admin"]:
            for i in range(1, count + 1):
                username = f"test_{role}_{i}"
                email = f"test_{role}_{i}@volunteer.test"
                User.objects.filter(username=username).delete()
                User.objects.filter(email=email).delete()
        print("✓ Existing test users deleted")

    # Create volunteers
    if "volunteer" in roles:
        print(f"\nCreating {count} volunteer test users...")
        for i in range(1, count + 1):
            username = f"test_volunteer_{i}"
            email = f"test_volunteer_{i}@volunteer.test"
            try:
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "email": email,
                        "first_name": f"Volunteer",
                        "last_name": f"Test{i}",
                    },
                )
                if created:
                    user.set_password(password)
                    user.save()

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.role = "volunteer"
                course_number = ((i - 1) % 4) + 1
                profile.group_name = f"IT-{course_number}{(i % 10) + 1}"
                profile.save()

                created_users.append(user)
                print(
                    f"  ✓ {username} (IT-{course_number}{(i % 10) + 1}) - password: {password}"
                )
            except Exception as e:
                print(f"  ✗ Error creating {username}: {e}")

    # Create organisers
    if "organiser" in roles:
        print(f"\nCreating {count} organiser test users...")
        for i in range(1, count + 1):
            username = f"test_organiser_{i}"
            email = f"test_organiser_{i}@volunteer.test"
            try:
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "email": email,
                        "first_name": f"Organiser",
                        "last_name": f"Test{i}",
                    },
                )
                if created:
                    user.set_password(password)
                    user.save()

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.role = "organiser"
                profile.save()

                created_users.append(user)
                print(f"  ✓ {username} - password: {password}")
            except Exception as e:
                print(f"  ✗ Error creating {username}: {e}")

    # Create admins
    if "admin" in roles:
        print(f"\nCreating {count} admin test users...")
        for i in range(1, count + 1):
            username = f"test_admin_{i}"
            email = f"test_admin_{i}@volunteer.test"
            try:
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "email": email,
                        "first_name": f"Admin",
                        "last_name": f"Test{i}",
                    },
                )
                if created:
                    user.set_password(password)
                    user.save()

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.role = "admin"
                profile.save()

                created_users.append(user)
                print(f"  ✓ {username} - password: {password}")
            except Exception as e:
                print(f"  ✗ Error creating {username}: {e}")

    print(f"\n✓ Successfully created {len(created_users)} test users!")
    return created_users


def create_test_projects(count=10, clear=False, min_volunteers=0, max_volunteers=0):
    """
    Create test projects with random organisers and volunteers.

    Args:
        count: Number of projects to create
        clear: Whether to delete existing test projects first
        min_volunteers: Minimum volunteers per project
        max_volunteers: Maximum volunteers per project (0 for unlimited)

    Returns:
        List of created projects
    """
    project_names = [
        "Збори пластику у парку",
        "Посадка дерев біля школи",
        "Прибирання берегової лінії",
        "Майстер-клас з рукоділля",
        "Тренінг з першої допомоги",
        "Організація благодійного ярмарку",
        "Пікник для дітей-сиріт",
        "Розбудова громадського простору",
        "Курс комп'ютерної грамотності",
        "Екологічна акція 'Чисте місто'",
        "Збір коштів на медобладнання",
        "Весняне прибирання району",
        "Фотосесія для ветеранів",
        "Міжнародний день волонтера",
        "Тренінг з орієнтування в місті",
        "Прибирання сміття в лісі",
        "Майстер-клас з малювання",
        "Спортивний захід для дітей",
        "Збір книг для бібліотеки",
        "Акція допомоги безпритульним тваринам",
    ]

    project_descriptions = [
        "Це чудова можливість допомогти нашому місту стати чистішим та зеленішим.",
        "Долучайтеся до важливої та корисної суспільної роботи!",
        "Разом ми можемо зробити більше для нашого спільноти.",
        "Чекаємо на активних та енергійних волонтерів!",
        "Відмінний спосіб провести час корисно та з користю для інших.",
        "Приєднуйтесь до нашої дружної команди волонтерів!",
    ]

    locations = [
        "Парк культури та відпочинку",
        "Центральна площа",
        "Берегова лінія річки",
        "Училище №1",
        "Міський парк",
        "Стадіон",
        "Громадський центр",
        "Бібліотека",
        "Музей",
        "Ботанічний сад",
    ]

    if clear:
        print("Deleting existing test projects...")
        # Delete requests first to avoid foreign key constraint errors
        Request.objects.filter(event__name__startswith="Тестовий проект").delete()
        for name in project_names:
            Request.objects.filter(event__name__startswith=name).delete()
        # Now delete the projects
        Project.objects.filter(name__startswith="Тестовий проект").delete()
        for name in project_names:
            Project.objects.filter(name__startswith=name).delete()
        print("✓ Existing test projects deleted")

    # Get all organisers
    organisers = User.objects.filter(
        profile__role__in=["organiser", "admin"]
    ).select_related("profile")

    if not organisers.exists():
        print("✗ No organisers found. Please create test organisers first.")
        print("  Run: python create_test_data.py --roles organiser,admin")
        return []

    # Get all volunteers
    volunteers = User.objects.filter(profile__role="volunteer").select_related(
        "profile"
    )

    if not volunteers.exists() and min_volunteers > 0:
        print("⚠ No volunteers found. Skipping volunteer assignments.")

    print(f"\nCreating {count} test projects...")
    statuses = ["apply", "pending", "approved", "rejected"]
    created_projects = []

    for i in range(1, count + 1):
        name = random.choice(project_names)
        organiser = random.choice(organisers)
        max_vol = random.choice([0, 5, 10, 15, 20])

        # Create project
        project = Project.objects.create(
            name=f"{name} #{i}",
            organiser=organiser,
            description=random.choice(project_descriptions),
            location=random.choice(locations),
            date=datetime.now() + timedelta(days=random.randint(1, 90)),
            hours=random.randint(2, 8),
            max_volunteers=max_vol,
            current_volunteers=0,
            status=random.choice(statuses),
        )

        created_projects.append(project)
        print(f"  ✓ {project.name}")
        print(f"    Organiser: {organiser.first_name or organiser.username}")
        print(
            f"    Location: {project.location} | Date: {project.date.strftime('%Y-%m-%d')}"
        )

        # Assign random volunteers if requested
        if volunteers.exists() and (min_volunteers > 0 or max_volunteers > 0):
            num_to_assign = (
                random.randint(min_volunteers, max(max_volunteers, min_volunteers))
                if max_volunteers > 0
                else min_volunteers
            )

            num_to_assign = min(num_to_assign, volunteers.count())

            if num_to_assign > 0:
                assigned_volunteers = random.sample(list(volunteers), num_to_assign)
                statuses_list = ["pending", "approved", "rejected", "completed"]

                for vol in assigned_volunteers:
                    status = random.choice(statuses_list)
                    request = Request.objects.create(
                        Volunteer=vol,
                        event=project,
                        status=status,
                        approved_hours=project.hours
                        if status in ["approved", "completed"]
                        else None,
                    )
                    if status == "approved":
                        project.current_volunteers += 1

                project.save()
                print(f"    Volunteers: {num_to_assign} assigned")

    print(f"\n✓ Successfully created {len(created_projects)} test projects!")
    return created_projects


def main():
    parser = argparse.ArgumentParser(
        description="Create test data for the volunteer system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of test users to create per role (default: 5)",
    )
    parser.add_argument(
        "--roles",
        type=str,
        default="volunteer,organiser,admin",
        help="Comma-separated list of roles (default: volunteer,organiser,admin)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete existing test data before creating new",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="test123456",
        help="Password for created users (default: test123456)",
    )
    parser.add_argument(
        "--create-projects-only",
        action="store_true",
        help="Only create projects, not users",
    )
    parser.add_argument(
        "--min-volunteers",
        type=int,
        default=0,
        help="Minimum volunteers per project (default: 0)",
    )
    parser.add_argument(
        "--max-volunteers",
        type=int,
        default=0,
        help="Maximum volunteers per project, 0 for unlimited (default: 0)",
    )
    parser.add_argument(
        "--project-count",
        type=int,
        default=10,
        help="Number of projects to create (default: 10)",
    )

    args = parser.parse_args()

    roles = [r.strip() for r in args.roles.split(",")]

    if args.create_projects_only:
        create_test_projects(
            count=args.project_count,
            clear=args.clear,
            min_volunteers=args.min_volunteers,
            max_volunteers=args.max_volunteers,
        )
    else:
        print("=" * 60)
        print("VOLUNTEER SYSTEM - TEST DATA GENERATOR")
        print("=" * 60)

        create_test_users(
            count=args.count,
            roles=roles,
            clear=args.clear,
            password=args.password,
        )

        if any(r in roles for r in ["organiser", "admin"]):
            print("\n" + "-" * 60)
            create_test_projects(
                count=args.project_count,
                clear=args.clear,
                min_volunteers=args.min_volunteers,
                max_volunteers=args.max_volunteers,
            )

        print("\n" + "=" * 60)
        print("✓ Test data generation complete!")
        print("=" * 60)
        print(f"\nAll users have password: {args.password}")
        print("\nTo login via API:")
        print("  POST http://localhost:8000/api/auth/login/")
        print(
            '  Body: {"email": "test_volunteer_1@volunteer.test", "password": "test123456"}'
        )


if __name__ == "__main__":
    main()
