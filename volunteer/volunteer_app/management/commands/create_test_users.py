from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from volunteer_app.models import UserProfile


class Command(BaseCommand):
    help = "Create test users with different roles (volunteer, organiser, admin)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Number of test users to create per role (default: 5)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all test users before creating new ones",
        )
        parser.add_argument(
            "--roles",
            type=str,
            default="volunteer,organiser,admin",
            help="Comma-separated list of roles to create (default: volunteer,organiser,admin)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        clear = options["clear"]
        roles = [r.strip() for r in options["roles"].split(",")]

        test_users = []

        if clear:
            self.stdout.write("Deleting existing test users...")
            for role in ["volunteer", "organiser", "admin"]:
                for i in range(1, count + 1):
                    username = f"test_{role}_{i}"
                    email = f"test_{role}_{i}@volunteer.test"
                    User.objects.filter(username=username).delete()
                    User.objects.filter(email=email).delete()
            self.stdout.write(self.style.SUCCESS("Existing test users deleted"))

        # Create volunteers
        if "volunteer" in roles:
            self.stdout.write(f"Creating {count} volunteer test users...")
            for i in range(1, count + 1):
                username = f"test_volunteer_{i}"
                email = f"test_volunteer_{i}@volunteer.test"
                try:
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults={
                            "email": email,
                            "first_name": "Volunteer",
                            "last_name": f"Test{i}",
                        },
                    )
                    if created:
                        user.set_password("test123456")
                        user.save()
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = "volunteer"
                    # Assign to different groups/courses for variety
                    course_number = ((i - 1) % 4) + 1  # 1, 2, 3, or 4
                    profile.group_name = f"IT-{course_number}{(i % 10) + 1}"
                    profile.save()
                    test_users.append(f"volunteer: {username}")
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Created: {username} (IT-{course_number}{(i % 10) + 1}) - test123456"
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  Error creating {username}: {e}")
                    )

        # Create organisers
        if "organiser" in roles:
            self.stdout.write(f"Creating {count} organiser test users...")
            for i in range(1, count + 1):
                username = f"test_organiser_{i}"
                email = f"test_organiser_{i}@volunteer.test"
                try:
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults={
                            "email": email,
                            "first_name": "Organiser",
                            "last_name": f"Test{i}",
                        },
                    )
                    if created:
                        user.set_password("test123456")
                        user.save()
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = "organiser"
                    profile.save()
                    test_users.append(f"organiser: {username}")
                    self.stdout.write(
                        self.style.SUCCESS(f"  Created: {username} - test123456")
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  Error creating {username}: {e}")
                    )

        # Create admins
        if "admin" in roles:
            self.stdout.write(f"Creating {count} admin test users...")
            for i in range(1, count + 1):
                username = f"test_admin_{i}"
                email = f"test_admin_{i}@volunteer.test"
                try:
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults={
                            "email": email,
                            "first_name": "Admin",
                            "last_name": f"Test{i}",
                        },
                    )
                    if created:
                        user.set_password("test123456")
                        user.save()
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = "admin"
                    profile.save()
                    test_users.append(f"admin: {username}")
                    self.stdout.write(
                        self.style.SUCCESS(f"  Created: {username} - test123456")
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  Error creating {username}: {e}")
                    )

        self.stdout.write(
            self.style.SUCCESS(f"\nSuccessfully created {len(test_users)} test users!")
        )
        self.stdout.write("\nAll test users have password: test123456")
        self.stdout.write("\nTo create test projects, run:")
        self.stdout.write("  python manage.py create_test_projects")
