from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from volunteer_app.models import (
    UserSubscription, PrioritySpot, VolunteerReview,
    Organization, Project, Request,
)
import random


class Command(BaseCommand):
    help = "Create test purchases: subscriptions, priority spots, reviews, organizations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all test purchase data before creating new",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            UserSubscription.objects.all().delete()
            PrioritySpot.objects.all().delete()
            VolunteerReview.objects.all().delete()
            Organization.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Старі дані видалено"))

        # ── Organizations ─────────────────────────────────────────────────────
        self.stdout.write("Створення організацій...")
        orgs_data = [
            {"name": "Bosco Youth", "slug": "bosco-youth",
             "site_name": "BoscoVolunteer", "description": "Молодіжна спільнота Боско"},
            {"name": "Green Campus", "slug": "green-campus",
             "site_name": "GreenCampus", "description": "Еко-волонтерство університету"},
            {"name": "IT Helpers", "slug": "it-helpers",
             "site_name": "ITHelpers", "description": "Технічна підтримка для НКО"},
        ]
        owner = User.objects.filter(is_superuser=True).first() or User.objects.first()
        created_orgs = []
        for data in orgs_data:
            org, created = Organization.objects.get_or_create(
                slug=data["slug"],
                defaults={**data, "owner": owner},
            )
            created_orgs.append(org)
            self.stdout.write(
                self.style.SUCCESS(f"  {'Створено' if created else 'Вже є'}: {org.name}")
            )

        # ── Analytics subscriptions (organisers) ──────────────────────────────
        self.stdout.write("Підписки на аналітику (організатори)...")
        organisers = list(
            User.objects.filter(profile__role="organiser")[:3]
        )
        for u in organisers:
            sub, created = UserSubscription.objects.get_or_create(
                user=u, plan_type="analytics",
                defaults={"is_active": True},
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {'Створено' if created else 'Вже є'}: {u.username} — analytics $10"
                )
            )

        # ── Premium subscriptions (mixed roles) ───────────────────────────────
        self.stdout.write("Преміум підписки...")
        premium_users = list(
            User.objects.filter(profile__role__in=["volunteer", "organiser", "admin"])[:4]
        )
        for u in premium_users:
            sub, created = UserSubscription.objects.get_or_create(
                user=u, plan_type="premium",
                defaults={"is_active": True},
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {'Створено' if created else 'Вже є'}: {u.username} — premium $20"
                )
            )

        # ── Priority spots (volunteers on full events) ─────────────────────────
        self.stdout.write("Пріоритетні місця...")
        full_projects = Project.objects.filter(max_volunteers__gt=0).filter(
            current_volunteers__gte=1
        )[:3]
        volunteers = list(User.objects.filter(profile__role="volunteer")[:5])
        spots_created = 0
        for project in full_projects:
            for v in volunteers[:2]:
                if Request.objects.filter(Volunteer=v, event=project).exists():
                    continue
                spot, created = PrioritySpot.objects.get_or_create(
                    volunteer=v, event=project
                )
                if created:
                    Request.objects.get_or_create(
                        Volunteer=v, event=project,
                        defaults={"status": "pending"},
                    )
                    spots_created += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Пріоритет: {v.username} → {project.name}"
                        )
                    )
        if spots_created == 0:
            self.stdout.write("  (немає переповнених подій, пріоритети не створено)")

        # ── Volunteer reviews ──────────────────────────────────────────────────
        self.stdout.write("Відгуки волонтерів...")
        completed_requests = Request.objects.filter(status="completed").select_related(
            "Volunteer", "event"
        )[:15]
        reviews_created = 0
        sample_comments = [
            "Чудовий досвід, дуже рада що взяла участь!",
            "Організація на вищому рівні, прийду ще раз",
            "Цікавий захід, але дуже втомлююча фізична робота",
            "Все було супер, дякую організаторам!",
            "Непоганий досвід, є над чим попрацювати",
            "Отримала багато нових навичок і знайомств",
            "Сподобалась атмосфера, все добре організовано",
            "",  # деякі без коментаря
            "",
        ]
        for req in completed_requests:
            if VolunteerReview.objects.filter(
                volunteer=req.Volunteer, event=req.event
            ).exists():
                continue
            rating = random.randint(3, 5)
            comment = random.choice(sample_comments)
            VolunteerReview.objects.create(
                volunteer=req.Volunteer,
                event=req.event,
                rating=rating,
                comment=comment,
            )
            reviews_created += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Відгук: {req.Volunteer.username} → {req.event.name}: {rating}★"
                )
            )

        if reviews_created == 0:
            self.stdout.write(
                "  (завершених заявок немає, відгуки не створено — "
                "спочатку запустіть create_test_projects і approve/complete заявки)"
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 50))
        self.stdout.write(self.style.SUCCESS("Підсумок:"))
        self.stdout.write(f"  Організацій:        {Organization.objects.count()}")
        self.stdout.write(f"  Підписок analytics: {UserSubscription.objects.filter(plan_type='analytics').count()}")
        self.stdout.write(f"  Підписок premium:   {UserSubscription.objects.filter(plan_type='premium').count()}")
        self.stdout.write(f"  Пріоритетних місць: {PrioritySpot.objects.count()}")
        self.stdout.write(f"  Відгуків:           {VolunteerReview.objects.count()}")
