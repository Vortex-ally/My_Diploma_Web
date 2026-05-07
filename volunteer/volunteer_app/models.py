from django.contrib.auth.models import User
from django.db import IntegrityError, models
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


class GroupTemplate(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="Назва групи")
    course = models.PositiveIntegerField(verbose_name="Курс")

    def __str__(self):
        return f"{self.name} ({self.course} курс)"

    class Meta:
        ordering = ["course", "name"]


class EventTemplate(models.Model):
    name = models.CharField(max_length=255, verbose_name="Назва шаблону")
    location = models.CharField(max_length=255, verbose_name="Місце проведення")
    description = models.TextField(blank=True, verbose_name="Опис")
    default_hours = models.PositiveIntegerField(verbose_name="Години за замовчуванням")
    icon = models.CharField(
        max_length=50, default="fas fa-calendar-check", verbose_name="Іконка"
    )
    color = models.CharField(max_length=20, default="#e0e7ff", verbose_name="Колір")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Шаблон заходу"
        verbose_name_plural = "Шаблони заходів"


class WorkTypeTemplate(models.Model):
    name = models.CharField(max_length=255, verbose_name="Тип роботи")
    description = models.TextField(blank=True, verbose_name="Опис")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Шаблон типу роботи"
        verbose_name_plural = "Шаблони типів робіт"


class HoursTemplate(models.Model):
    name = models.CharField(max_length=100, verbose_name="Назва")
    hours = models.PositiveIntegerField(verbose_name="Години")
    description = models.CharField(max_length=255, blank=True, verbose_name="Опис")

    def __str__(self):
        return f"{self.name} - {self.hours} год"

    class Meta:
        verbose_name = "Шаблон годин"
        verbose_name_plural = "Шаблони годин"
        ordering = ["hours"]


class Message(models.Model):
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_messages"
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="received_messages"
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sender} -> {self.recipient}: {self.content[:30]}..."

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Повідомлення"
        verbose_name_plural = "Повідомлення"


class ArchiveRequest(models.Model):
    volunteer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="archived_requests"
    )
    event = models.ForeignKey("Project", on_delete=models.CASCADE)
    date_requested = models.DateTimeField()
    date_completed = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20)
    approved_hours = models.PositiveIntegerField(null=True, blank=True)
    organizer_report = models.TextField(blank=True, null=True)
    star_rating = models.BooleanField(default=False)
    archived_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Архів: {self.volunteer.username} - {self.event.name}"

    class Meta:
        verbose_name = "Архівна заявка"
        verbose_name_plural = "Архів заявок"
        ordering = ["-archived_at"]


class VolunteerGoal(models.Model):
    volunteer = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="volunteer_goal"
    )
    target_hours = models.PositiveIntegerField(verbose_name="Цільова кількість годин")
    current_hours = models.PositiveIntegerField(
        default=0, verbose_name="Поточні години"
    )
    completed = models.BooleanField(default=False, verbose_name="Ціль досягнута")

    def __str__(self):
        return (
            f"{self.volunteer.username}: {self.current_hours}/{self.target_hours} год"
        )

    def get_progress_percentage(self):
        if self.target_hours == 0:
            return 100
        return min(100, (self.current_hours / self.target_hours) * 100)

    class Meta:
        verbose_name = "Ціль волонтера"
        verbose_name_plural = "Цілі волонтерів"


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ("volunteer", "Волонтер"),
        ("organiser", "Організатор"),
        ("admin", "Адміністратор"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="volunteer")
    group_name = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Група (наприклад, IT-21)"
    )

    def __str__(self):
        return f"{self.user.username} - {self.role}"


@receiver(post_save, sender=User)
def create_or_save_user_profile(sender, instance, created, **kwargs):
    if created:
        if not UserProfile.objects.filter(user=instance).exists():
            try:
                UserProfile.objects.create(user=instance)
            except IntegrityError:
                pass


class Organization(models.Model):
    name = models.CharField(max_length=255, verbose_name="Назва організації")
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, verbose_name="Опис")
    site_name = models.CharField(max_length=100, default="BoscoVolunteer", verbose_name="Назва сайту")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_organizations")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Організація"
        verbose_name_plural = "Організації"


class Project(models.Model):
    ACTION = [
        ("apply", "Подати заявку"),
        ("approved", "Схвалено"),
        ("pending", "Заявку подано"),
        ("rejected", "Заявку відхилено"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="", verbose_name="Опис")
    location = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Місце проведення"
    )
    organiser = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="organised_projects"
    )
    date = models.DateTimeField()
    hours = models.PositiveIntegerField()
    max_volunteers = models.PositiveIntegerField(
        default=0, verbose_name="Максимальна кількість волонтерів (0 - без обмежень)"
    )
    current_volunteers = models.PositiveIntegerField(
        default=0, verbose_name="Поточ кількість волонтерів"
    )
    status = models.CharField(max_length=20, choices=ACTION, default="apply")
    price = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, verbose_name="Вартість участі ($)"
    )
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="projects", verbose_name="Організація"
    )

    def __str__(self):
        return self.name


class Rating(models.Model):
    name = models.ForeignKey(User, related_name="ratings", on_delete=models.CASCADE)
    rating = models.PositiveIntegerField()

    def __str__(self):
        return self.name


class Request(models.Model):
    STATUS_CHOICES = [
        ("pending", "В очікуванні"),
        ("approved", "Схвалено"),
        ("completed", "Відпрацьовано"),
        ("rejected", "Відхилено"),
    ]
    Volunteer = models.ForeignKey(
        User, related_name="requests", on_delete=models.CASCADE
    )
    event = models.ForeignKey(
        Project, related_name="requests", on_delete=models.DO_NOTHING
    )
    date_requested = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    approved_hours = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Зараховані години"
    )
    organizer_report = models.TextField(
        blank=True, null=True, verbose_name="Скарга організатора"
    )
    organizer_reported = models.BooleanField(
        default=False, verbose_name="Поскаржено організатором"
    )
    star_rating = models.BooleanField(
        default=False, verbose_name="Зірочка за гарну роботу"
    )

    def __str__(self):
        return f"{self.Volunteer.username} -> {self.event.name} ({self.status})"


class VolunteerReview(models.Model):
    volunteer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews_given")
    event = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveIntegerField(
        choices=[(i, f"{i} ★") for i in range(1, 6)], verbose_name="Оцінка"
    )
    comment = models.TextField(blank=True, verbose_name="Коментар")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("volunteer", "event")
        verbose_name = "Відгук волонтера"
        verbose_name_plural = "Відгуки волонтерів"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.volunteer.username} → {self.event.name}: {self.rating}★"


class UserSubscription(models.Model):
    PLAN_CHOICES = [
        ("analytics", "Розширена аналітика ($10)"),
        ("premium", "Преміум акаунт ($20)"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    plan_type = models.CharField(max_length=20, choices=PLAN_CHOICES)
    purchased_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "plan_type")
        verbose_name = "Підписка"
        verbose_name_plural = "Підписки"

    def __str__(self):
        return f"{self.user.username} – {self.plan_type}"


class PrioritySpot(models.Model):
    volunteer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="priority_spots")
    event = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="priority_spots")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("volunteer", "event")
        verbose_name = "Пріоритетне місце"
        verbose_name_plural = "Пріоритетні місця"

    def __str__(self):
        return f"{self.volunteer.username} – {self.event.name}"


# ─── Telegram integration ─────────────────────────────────────────────────────

class TelegramUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="telegram")
    chat_id = models.BigIntegerField(unique=True)
    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TG {self.user.username} → {self.chat_id}"

    class Meta:
        verbose_name = "Telegram-акаунт"
        verbose_name_plural = "Telegram-акаунти"


class TelegramNotification(models.Model):
    chat_id = models.BigIntegerField(db_index=True)
    message = models.TextField()
    is_sent = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "TG-сповіщення"
        verbose_name_plural = "TG-сповіщення"

    def __str__(self):
        return f"TG {self.chat_id}: {self.message[:40]}"


def _tg_notify(chat_id, message):
    """Queue one Telegram notification (never raises)."""
    try:
        TelegramNotification.objects.create(chat_id=chat_id, message=message)
    except Exception:
        pass


def _tg_notify_admins(message):
    """Queue notification for every linked admin / superuser."""
    try:
        admin_chat_ids = (
            TelegramUser.objects
            .filter(is_active=True)
            .filter(
                models.Q(user__is_superuser=True) |
                models.Q(user__profile__role="admin")
            )
            .values_list("chat_id", flat=True)
        )
        for cid in admin_chat_ids:
            _tg_notify(cid, message)
    except Exception:
        pass


# ── Track old Request status to avoid duplicate notifications ─────────────────
_req_old: dict = {}


@receiver(pre_save, sender="volunteer_app.Request")
def _capture_request_state(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            _req_old[instance.pk] = (old.status, old.organizer_reported)
        except sender.DoesNotExist:
            pass


@receiver(post_save, sender="volunteer_app.Request")
def _notify_on_request_change(sender, instance, created, **kwargs):
    volunteer = instance.Volunteer
    event_name = instance.event.name

    # New application → organizer
    if created:
        try:
            cid = instance.event.organiser.telegram.chat_id
            name = volunteer.get_full_name() or volunteer.username
            _tg_notify(cid, f"📋 Нова заявка від *{name}* на «{event_name}»")
        except Exception:
            pass
        return

    old_status, old_reported = _req_old.pop(instance.pk, (None, False))

    # Approved → volunteer
    if instance.status == "approved" and old_status != "approved":
        try:
            _tg_notify(volunteer.telegram.chat_id,
                       f"✅ Вашу заявку на «{event_name}» *схвалено*!")
        except Exception:
            pass

    # Completed → volunteer
    if instance.status == "completed" and old_status != "completed":
        try:
            hours = instance.approved_hours or instance.event.hours
            _tg_notify(volunteer.telegram.chat_id,
                       f"🎉 Вам зараховано *{hours} год* за «{event_name}»!")
        except Exception:
            pass

    # Rejected → volunteer
    if instance.status == "rejected" and old_status != "rejected":
        try:
            _tg_notify(volunteer.telegram.chat_id,
                       f"❌ Вашу заявку на «{event_name}» відхилено.")
        except Exception:
            pass

    # New complaint → admins
    if instance.organizer_reported and not old_reported:
        report_text = (instance.organizer_report or "")[:200]
        vol_name = volunteer.get_full_name() or volunteer.username
        _tg_notify_admins(
            f"🚨 Скарга на волонтера *{vol_name}*\n"
            f"Подія: «{event_name}»\n"
            f"Текст: {report_text}"
        )


@receiver(post_save, sender="volunteer_app.Project")
def _notify_on_new_project(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        date_str = instance.date.strftime("%d.%m.%Y %H:%M") if instance.date else "—"
        msg = (
            f"🆕 Нове волонтерське завдання!\n"
            f"*{instance.name}*\n"
            f"📅 {date_str}  ⏰ {instance.hours} год"
        )
        chat_ids = (
            TelegramUser.objects
            .filter(is_active=True, user__profile__role="volunteer")
            .values_list("chat_id", flat=True)
        )
        for cid in chat_ids:
            _tg_notify(cid, msg)
    except Exception:
        pass
