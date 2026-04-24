from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from volunteer_app.models import Project, Request
import random
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = "Create test projects with random organisers and volunteers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of test projects to create (default: 10)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all test projects before creating new ones",
        )
        parser.add_argument(
            "--min-volunteers",
            type=int,
            default=0,
            help="Minimum number of volunteers per project (default: 0)",
        )
        parser.add_argument(
            "--max-volunteers",
            type=int,
            default=0,
            help="Maximum number of volunteers per project, 0 for unlimited (default: 0)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        clear = options["clear"]
        min_volunteers = options["min_volunteers"]
        max_volunteers = options["max_volunteers"]

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
            self.stdout.write("Deleting existing test projects...")
            Project.objects.filter(name__startswith="Тестовий проект").delete()
            self.stdout.write(self.style.SUCCESS("Existing test projects deleted"))

        # Get all organisers
        organisers = User.objects.filter(
            profile__role__in=["organiser", "admin"]
        ).select_related("profile")

        if not organisers.exists():
            self.stdout.write(
                self.style.WARNING(
                    "No organisers found. Please create test organisers first:"
                )
            )
            self.stdout.write(
                "  python manage.py create_test_users --roles organiser,admin"
            )
            return

        # Get all volunteers
        volunteers = User.objects.filter(profile__role="volunteer").select_related(
            "profile"
        )

        if not volunteers.exists() and min_volunteers > 0:
            self.stdout.write(
                self.style.WARNING(
                    "No volunteers found. Skipping volunteer assignments."
                )
            )

        self.stdout.write(f"Creating {count} test projects...")
        statuses = ["apply", "pending", "approved", "rejected"]

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

            self.stdout.write(
                self.style.SUCCESS(
                    f"  Created: {project.name} (by {organiser.first_name or organiser.username}) - {project.location}"
                )
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
                    self.stdout.write(f"    Assigned {num_to_assign} volunteers")

        self.stdout.write(
            self.style.SUCCESS(f"\nSuccessfully created {count} test projects!")
        )
        self.stdout.write("\nProjects created with random:")
        self.stdout.write("  - Organisers (from existing organiser/admin users)")
        self.stdout.write("  - Locations")
        self.stdout.write("  - Dates (within next 90 days)")
        self.stdout.write("  - Statuses")
        if volunteers.exists():
            self.stdout.write("  - Volunteer assignments (if specified)")
