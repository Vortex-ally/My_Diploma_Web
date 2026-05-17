from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (
    ArchiveRequest,
    EventTemplate,
    GroupTemplate,
    HoursTemplate,
    Message,
    Organization,
    PrioritySpot,
    Project,
    Rating,
    Request,
    UserProfile,
    UserSubscription,
    VolunteerGoal,
    VolunteerReview,
    WorkTypeTemplate,
)


# Define an inline admin descriptor for UserProfile model
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Профіль користувача"
    extra = 0
    max_num = 1
    fields = ("role", "group_name")

    def has_add_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return True


# Define a new User admin
class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "get_role",
        "get_group",
    )
    list_filter = ("is_staff", "is_superuser", "profile__role")
    search_fields = ("username", "email", "first_name", "last_name")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Персональна інформація", {"fields": ("first_name", "last_name", "email")}),
        (
            "Права",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Важливі дати", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                ),
            },
        ),
    )

    def get_role(self, instance):
        return instance.profile.role if hasattr(instance, "profile") else None

    get_role.short_description = "Роль"

    def get_group(self, instance):
        return instance.profile.group_name if hasattr(instance, "profile") else None

    get_group.short_description = "Група"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Create or update UserProfile
        if hasattr(obj, "profile"):
            profile = obj.profile
        else:
            profile = UserProfile.objects.create(user=obj)

        # Set role from form if provided
        if "role" in form.cleaned_data:
            profile.role = form.cleaned_data["role"]
        if "group_name" in form.cleaned_data:
            profile.group_name = form.cleaned_data["group_name"]
        profile.save()


# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organiser", "date", "hours", "max_volunteers", "status", "organization")
    list_filter = ("status", "organization")
    search_fields = ("name", "organiser__username")
    autocomplete_fields = ("organiser", "organization")


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ("Volunteer", "event", "status", "date_requested", "approved_hours")
    list_filter = ("status",)
    search_fields = ("Volunteer__username", "event__name")
    autocomplete_fields = ("Volunteer", "event")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "site_name", "created_at")
    search_fields = ("name", "owner__username")
    prepopulated_fields = {"slug": ("name",)}


admin.site.register(GroupTemplate)
admin.site.register(EventTemplate)
admin.site.register(WorkTypeTemplate)
admin.site.register(HoursTemplate)
admin.site.register(VolunteerGoal)
admin.site.register(VolunteerReview)
admin.site.register(UserSubscription)
admin.site.register(PrioritySpot)
admin.site.register(ArchiveRequest)
admin.site.register(Message)
admin.site.register(Rating)
