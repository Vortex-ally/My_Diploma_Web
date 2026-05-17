import json
import random
import string
import time
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Avg, Count, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import OrganizationForm, PaymentForm, ProjectForm, VolunteerReviewForm
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
    UserAuthToken,
    UserProfile,
    UserSubscription,
    VolunteerGoal,
    VolunteerReview,
    WorkTypeTemplate,
)

# ─── Payment plan constants ───────────────────────────────────────────────────

PLAN_PRICES = {
    "analytics": 10,
    "premium": 20,
    "priority": 1,
}

PLAN_LABELS = {
    "analytics": "Розширена аналітика",
    "premium": "Преміум акаунт",
    "priority": "Пріоритетне місце",
}


# ─── Utilities ────────────────────────────────────────────────────────────────


def extract_course(group_name):
    """Extract course number from group name (e.g., IT-21 -> 2, IT-11 -> 1)"""
    if not group_name:
        return None
    for char in group_name:
        if char.isdigit():
            return int(char)
    return None


def _calculate_volunteer_hours(user):
    """Return total approved/completed volunteer hours for a user."""
    total = 0
    for r in Request.objects.filter(
        Volunteer=user, status__in=["approved", "completed"]
    ).select_related("event"):
        total += r.approved_hours if r.approved_hours is not None else (r.event.hours or 0)
    return total


def _build_ratings_context(volunteer_qs=None):
    """Return [{name: User, rating: hours}, ...] ordered by hours desc."""
    if volunteer_qs is None:
        volunteer_qs = User.objects.filter(profile__role="volunteer")
    volunteers = (
        volunteer_qs.select_related("profile")
        .annotate(
            total_hours=Coalesce(
                Sum("requests__event__hours", filter=Q(requests__status="approved")),
                0,
            )
        )
        .order_by("-total_hours", "username")
    )
    return [{"name": u, "rating": u.total_hours} for u in volunteers]


def _build_courses_list():
    """Return sorted list of unique course numbers from volunteer group names."""
    courses = set()
    for group_name in (
        UserProfile.objects.filter(role="volunteer")
        .exclude(group_name__isnull=True)
        .exclude(group_name="")
        .values_list("group_name", flat=True)
    ):
        c = extract_course(group_name)
        if c:
            courses.add(c)
    return sorted(courses | {1, 2})


def _build_premium_stats():
    """Return revenue/subscription statistics dict for admin dashboard."""
    premium_count = UserSubscription.objects.filter(
        plan_type="premium", is_active=True
    ).count()
    analytics_only_count = UserSubscription.objects.filter(
        plan_type="analytics", is_active=True
    ).count()
    analytics_count = UserSubscription.objects.filter(
        plan_type__in=["analytics", "premium"], is_active=True
    ).count()
    priority_count = PrioritySpot.objects.count()
    return {
        "premium_sub_count": premium_count,
        "analytics_sub_count": analytics_count,
        "priority_spot_count": priority_count,
        "total_revenue": premium_count * 20 + analytics_only_count * 10 + priority_count,
        "org_count": Organization.objects.count(),
        "review_count": VolunteerReview.objects.count(),
    }


# ─── Dashboard context builders ──────────────────────────────────────────────


def _volunteer_dashboard_ctx(user):
    """Build template name + context dict for volunteer dashboard."""
    user_requests = Request.objects.filter(Volunteer=user)

    user_req_subquery = Request.objects.filter(
        Volunteer=user, event=OuterRef("pk")
    ).values("status")[:1]

    has_premium = UserSubscription.objects.filter(
        user=user, plan_type="premium", is_active=True
    ).exists()

    context = {
        "profile": user.profile,
        "projects": Project.objects.all().order_by("-date"),
        "activities": user_requests.order_by("-date_requested"),
        "joined_opportunities": user_requests.filter(status="approved"),
        "opportunities": Project.objects.annotate(
            application_status=Subquery(user_req_subquery)
        ).order_by("-date"),
        "ratings": _build_ratings_context(),
        "has_premium": has_premium,
        "premium_user_ids": list(
            UserSubscription.objects.filter(plan_type="premium", is_active=True)
            .values_list("user_id", flat=True)
        ),
        "completed_requests": Request.objects.filter(
            Volunteer=user, status="completed"
        ).select_related("event"),
        "reviewed_event_ids": list(
            VolunteerReview.objects.filter(volunteer=user).values_list(
                "event_id", flat=True
            )
        ),
        "priority_event_ids": list(
            PrioritySpot.objects.filter(volunteer=user).values_list(
                "event_id", flat=True
            )
        ),
    }

    try:
        goal = VolunteerGoal.objects.get(volunteer=user)
        context["volunteer_goal"] = goal
        context["progress_percent"] = goal.get_progress_percentage()
    except VolunteerGoal.DoesNotExist:
        course = extract_course(user.profile.group_name)
        target = 10 if course == 1 else 20
        context["volunteer_goal"] = {"target_hours": target, "current_hours": 0}
        context["progress_percent"] = 0

    if has_premium:
        approved_reqs = Request.objects.filter(status="approved").select_related(
            "Volunteer__profile", "event"
        )
        attendees_map = {}
        for req in approved_reqs:
            attendees_map.setdefault(req.event_id, []).append(req.Volunteer)
        context["attendees_by_event"] = attendees_map

    return "volunteer_app/user_dashboard.html", context


def _organiser_dashboard_ctx(user):
    """Build template name + context dict for organiser dashboard."""
    context = {
        "profile": user.profile,
        "projects": Project.objects.filter(organiser=user).order_by("-date"),
        "applicants": Request.objects.filter(event__organiser=user).order_by(
            "-date_requested"
        ),
        "project_form": ProjectForm(),
        "all_users": (
            User.objects.all()
            .select_related("profile")
            .annotate(
                total_hours=Coalesce(
                    Sum(
                        "requests__event__hours",
                        filter=Q(requests__status="approved"),
                    ),
                    0,
                )
            )
        ),
        "groups": (
            UserProfile.objects.filter(role="volunteer")
            .exclude(group_name__isnull=True)
            .exclude(group_name="")
            .values_list("group_name", flat=True)
            .distinct()
            .order_by("group_name")
        ),
        "event_templates": EventTemplate.objects.all(),
        "work_type_templates": WorkTypeTemplate.objects.all(),
        "hours_templates": HoursTemplate.objects.all(),
        "has_analytics": UserSubscription.objects.filter(
            user=user, plan_type__in=["analytics", "premium"], is_active=True
        ).exists(),
        "has_premium": UserSubscription.objects.filter(
            user=user, plan_type="premium", is_active=True
        ).exists(),
        "organizations": Organization.objects.all(),
    }
    return "volunteer_app/organizer_dashboard.html", context


def _admin_dashboard_ctx(user, request):
    """Build template name + context dict for admin/superuser dashboard."""
    all_users = list(
        User.objects.all()
        .select_related("profile")
        .annotate(
            total_hours=Coalesce(
                Sum("requests__event__hours", filter=Q(requests__status="approved")),
                0,
            )
        )
    )
    for u in all_users:
        group_name = getattr(getattr(u, "profile", None), "group_name", None)
        u.course = extract_course(group_name) if group_name else None
    all_users.sort(key=lambda x: (x.course is None, x.course or 0))

    imported_students = request.session.pop("imported_students", None)

    context = {
        "profile": getattr(user, "profile", None),
        "all_users": all_users,
        "volunteer_count": UserProfile.objects.filter(role="volunteer").count(),
        "organizer_count": UserProfile.objects.filter(role="organiser").count(),
        "projects": Project.objects.all().order_by("-date"),
        "all_requests": Request.objects.all().order_by("-date_requested"),
        "ratings": _build_ratings_context(),
        "courses": _build_courses_list(),
        "groups": (
            UserProfile.objects.filter(role="volunteer")
            .exclude(group_name__isnull=True)
            .exclude(group_name="")
            .values_list("group_name", flat=True)
            .distinct()
            .order_by("group_name")
        ),
        "group_templates": GroupTemplate.objects.all(),
        "event_templates": EventTemplate.objects.all(),
        "work_type_templates": WorkTypeTemplate.objects.all(),
        "hours_templates": HoursTemplate.objects.all(),
        "has_premium": UserSubscription.objects.filter(
            user=user, plan_type="premium", is_active=True
        ).exists(),
        "premium_stats": _build_premium_stats(),
        "organizations": Organization.objects.all(),
    }
    if imported_students:
        context["imported_students"] = imported_students
    return "volunteer_app/admin_dashboard.html", context


# ─── Token auth ───────────────────────────────────────────────────────────────


def get_user_from_token(request):
    """Resolve the authenticated user from the `Authorization: Token <key>` header."""
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Token "):
        return None
    token = auth_header[len("Token "):].strip()
    try:
        return UserAuthToken.objects.select_related("user").get(key=token).user
    except UserAuthToken.DoesNotExist:
        return None


def api_auth_required(view_func):
    """Decorator that resolves the user from a token header before invoking the view."""

    def wrapper(request, *args, **kwargs):
        user = get_user_from_token(request)
        if user is None:
            return JsonResponse({"message": "Не авторизовано"}, status=401)
        request.user = user
        return view_func(request, *args, **kwargs)

    return wrapper


# ─── API helpers ──────────────────────────────────────────────────────────────


def _serialize_project(p, user=None):
    application_status = None
    has_priority = False
    if user is not None and user.is_authenticated:
        req = Request.objects.filter(event=p, Volunteer=user).first()
        if req:
            application_status = req.status
        has_priority = PrioritySpot.objects.filter(volunteer=user, event=p).exists()
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "location": p.location or "",
        "organiser_id": p.organiser.id,
        "organiser_name": p.organiser.first_name or p.organiser.username,
        "date": p.date.isoformat() if p.date else None,
        "hours": p.hours,
        "max_volunteers": p.max_volunteers,
        "current_volunteers": p.current_volunteers,
        "status": p.status,
        "price": float(p.price) if p.price is not None else 0.0,
        "application_status": application_status,
        "has_priority": has_priority,
    }


# ─── Auth API ─────────────────────────────────────────────────────────────────


@csrf_exempt
def api_login(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get("email")
            password = data.get("password")

            user_obj = User.objects.filter(
                Q(email__iexact=email) | Q(username__iexact=email)
            ).first()

            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password)

                if user is not None:
                    profile = getattr(user, "profile", None)
                    role = profile.role if profile else "user"
                    auth_token = UserAuthToken.generate_for(user)
                    return JsonResponse(
                        {
                            "token": auth_token.key,
                            "user": {
                                "id": user.id,
                                "username": user.username,
                                "name": user.first_name or user.username,
                                "first_name": user.first_name,
                                "last_name": user.last_name,
                                "email": user.email,
                                "role": role,
                                "group_name": profile.group_name if profile else None,
                            },
                        }
                    )
                else:
                    return JsonResponse({"message": "Невірний пароль"}, status=401)
            else:
                return JsonResponse({"message": "Користувача не знайдено"}, status=401)
        except Exception as e:
            return JsonResponse({"message": str(e)}, status=400)

    return JsonResponse({"message": "Method not allowed"}, status=405)


# ─── Projects API ─────────────────────────────────────────────────────────────


@csrf_exempt
def api_projects(request):
    if request.method == "GET":
        user = get_user_from_token(request)
        if user is not None:
            request.user = user

        if (
            user is not None
            and hasattr(user, "profile")
            and user.profile.role == "organiser"
        ):
            projects = Project.objects.filter(organiser=user).order_by("-date")
        else:
            projects = Project.objects.all().order_by("-date")

        data = [_serialize_project(p, user=user) for p in projects]
        return JsonResponse({"projects": data})

    if request.method == "POST":
        user = get_user_from_token(request)
        if user is None:
            return JsonResponse({"message": "Не авторизовано"}, status=401)
        try:
            data = json.loads(request.body)
            project = Project.objects.create(
                name=data.get("name"),
                organiser=user,
                date=timezone.now() + timedelta(days=int(data.get("days", 1))),
                hours=int(data.get("hours", 1)),
                max_volunteers=int(data.get("max_volunteers", 0)),
            )
            return JsonResponse({"project": {"id": project.id}})
        except Exception as e:
            return JsonResponse({"message": str(e)}, status=400)

    return JsonResponse({"message": "Method not allowed"}, status=405)


@csrf_exempt
def api_project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == "GET":
        user = get_user_from_token(request)
        return JsonResponse({"project": _serialize_project(project, user=user)})

    user = get_user_from_token(request)
    if user is None:
        return JsonResponse({"message": "Не авторизовано"}, status=401)

    if request.method == "PUT":
        if project.organiser != user:
            return JsonResponse({"message": "Немає доступу"}, status=403)
        try:
            data = json.loads(request.body)
            project.name = data.get("name", project.name)
            project.description = data.get("description", project.description)
            project.hours = int(data.get("hours", project.hours))
            project.max_volunteers = int(
                data.get("max_volunteers", project.max_volunteers)
            )
            project.status = data.get("status", project.status)
            project.save()
            return JsonResponse({"project": {"id": project.id}})
        except Exception as e:
            return JsonResponse({"message": str(e)}, status=400)

    if request.method == "DELETE":
        if project.organiser != user:
            return JsonResponse({"message": "Немає доступу"}, status=403)
        project.delete()
        return JsonResponse({"message": "Проект видалено"})

    return JsonResponse({"message": "Method not allowed"}, status=405)


@csrf_exempt
@api_auth_required
def api_apply(request, project_id):
    if request.method != "POST":
        return JsonResponse({"message": "Method not allowed"}, status=405)

    project = get_object_or_404(Project, id=project_id)
    if project.organiser == request.user:
        return JsonResponse(
            {"message": "Не можна подати заявку на власний проект"}, status=400
        )

    existing = Request.objects.filter(event=project, Volunteer=request.user).first()
    if existing:
        return JsonResponse({"message": "Заявка вже подана"}, status=400)

    req = Request.objects.create(
        event=project, Volunteer=request.user, status="pending"
    )
    return JsonResponse({"application": {"id": req.id}})


@csrf_exempt
@api_auth_required
def api_my_applications(request):
    if request.method != "GET":
        return JsonResponse({"message": "Method not allowed"}, status=405)

    apps = (
        Request.objects.filter(Volunteer=request.user)
        .select_related("event")
        .order_by("-date_requested")
    )
    reviewed_event_ids = set(
        VolunteerReview.objects.filter(volunteer=request.user).values_list(
            "event_id", flat=True
        )
    )
    data = []
    for a in apps:
        data.append(
            {
                "id": a.id,
                "project_id": a.event.id,
                "project_name": a.event.name,
                "project_date": a.event.date.isoformat() if a.event.date else None,
                "project_hours": a.event.hours,
                "project_location": a.event.location or "",
                "status": a.status,
                "approved_hours": a.approved_hours,
                "star_rating": a.star_rating,
                "organizer_report": a.organizer_report,
                "date": a.date_requested.isoformat(),
                "can_review": a.status == "completed"
                and a.event.id not in reviewed_event_ids,
            }
        )
    return JsonResponse({"applications": data})


@csrf_exempt
def api_project_applications(request, project_id):
    if request.method == "GET":
        project = get_object_or_404(Project, id=project_id)
        apps = Request.objects.filter(event=project)
        data = [
            {
                "id": a.id,
                "user_id": a.Volunteer.id,
                "user_name": a.Volunteer.first_name or a.Volunteer.username,
                "user_email": a.Volunteer.email,
                "status": a.status,
                "date": a.date_requested.isoformat(),
            }
            for a in apps
        ]
        return JsonResponse({"applications": data})

    if request.method == "PUT" and request.user.is_authenticated:
        project = get_object_or_404(Project, id=project_id)
        if project.organiser != request.user:
            return JsonResponse({"message": "Немає доступу"}, status=403)

        try:
            data = json.loads(request.body)
            app_id = data.get("application_id")
            action = data.get("action")

            req = get_object_or_404(Request, id=app_id)
            old_status = req.status

            if action == "approve":
                req.status = "approved"
                req.save()
                if old_status != "approved" and project.max_volunteers > 0:
                    Project.objects.filter(id=project.id).update(
                        current_volunteers=F("current_volunteers") + 1
                    )
            elif action == "reject":
                req.status = "rejected"
                req.save()
                if old_status == "approved" and project.max_volunteers > 0:
                    Project.objects.filter(
                        id=project.id, current_volunteers__gt=0
                    ).update(current_volunteers=F("current_volunteers") - 1)

            return JsonResponse({"message": "OK"})
        except Exception as e:
            return JsonResponse({"message": str(e)}, status=400)

    return JsonResponse({"message": "Method not allowed"}, status=405)


# ─── Users API ────────────────────────────────────────────────────────────────


@csrf_exempt
def api_users(request):
    if request.method == "GET" and request.user.is_authenticated:
        if hasattr(request.user, "profile") and request.user.profile.role == "admin":
            users = User.objects.all()
            data = [
                {
                    "id": u.id,
                    "name": u.first_name or u.username,
                    "email": u.email,
                    "role": getattr(u, "profile", None).role
                    if hasattr(u, "profile")
                    else "user",
                    "is_active": u.is_active,
                }
                for u in users
            ]
            return JsonResponse({"users": data})
        return JsonResponse({"message": "Немає доступу"}, status=403)

    if request.method == "DELETE" and request.user.is_authenticated:
        if hasattr(request.user, "profile") and request.user.profile.role == "admin":
            try:
                data = json.loads(request.body)
                user_id = data.get("user_id")
                user = get_object_or_404(User, id=user_id)
                user.delete()
                return JsonResponse({"message": "Користувача видалено"})
            except Exception as e:
                return JsonResponse({"message": str(e)}, status=400)
        return JsonResponse({"message": "Немає доступу"}, status=403)

    return JsonResponse({"message": "Method not allowed"}, status=405)


# ─── Volunteer-facing JSON API ────────────────────────────────────────────────


@csrf_exempt
@api_auth_required
def api_profile(request):
    if request.method != "GET":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    user = request.user
    profile = getattr(user, "profile", None)
    total_events = Request.objects.filter(
        Volunteer=user, status__in=["approved", "completed"]
    ).count()
    total_hours = _calculate_volunteer_hours(user)
    star_count = Request.objects.filter(Volunteer=user, star_rating=True).count()
    return JsonResponse(
        {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "name": user.first_name or user.username,
                "role": profile.role if profile else "user",
                "group_name": profile.group_name if profile else None,
                "date_joined": user.date_joined.isoformat()
                if user.date_joined
                else None,
            },
            "stats": {
                "total_events": total_events,
                "total_hours": total_hours,
                "star_count": star_count,
            },
        }
    )


@csrf_exempt
@api_auth_required
def api_profile_update(request):
    if request.method != "POST":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"message": "Невірний формат запиту"}, status=400)
    user = request.user
    user.first_name = (data.get("first_name") or "").strip()
    user.last_name = (data.get("last_name") or "").strip()
    user.save()
    profile = getattr(user, "profile", None)
    if profile is not None:
        group_name = data.get("group_name")
        if group_name is not None:
            profile.group_name = group_name.strip() or None
        profile.save()
    return JsonResponse({"message": "Профіль оновлено"})


@csrf_exempt
@api_auth_required
def api_password_change(request):
    if request.method != "POST":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"message": "Невірний формат запиту"}, status=400)
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""
    if not request.user.check_password(current):
        return JsonResponse({"message": "Поточний пароль невірний"}, status=400)
    if len(new) < 6:
        return JsonResponse(
            {"message": "Пароль повинен містити мінімум 6 символів"}, status=400
        )
    request.user.set_password(new)
    request.user.save()
    new_token = UserAuthToken.generate_for(request.user)
    return JsonResponse({"message": "Пароль змінено", "token": new_token.key})


@csrf_exempt
@api_auth_required
def api_goal(request):
    user = request.user
    if not (hasattr(user, "profile") and user.profile.role == "volunteer"):
        return JsonResponse({"message": "Тільки для волонтерів"}, status=403)

    current_hours = _calculate_volunteer_hours(user)

    if request.method == "GET":
        try:
            goal = VolunteerGoal.objects.get(volunteer=user)
            target = goal.target_hours
            has_goal = True
        except VolunteerGoal.DoesNotExist:
            course = extract_course(user.profile.group_name) or 1
            target = 10 if course == 1 else 20
            has_goal = False
        progress = min(100.0, (current_hours / target) * 100.0) if target else 100.0
        return JsonResponse(
            {
                "goal": {
                    "target_hours": target,
                    "current_hours": current_hours,
                    "completed": current_hours >= target if target else True,
                    "progress_percentage": round(progress, 1),
                    "has_goal": has_goal,
                }
            }
        )

    if request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
        except Exception:
            data = {}
        course = extract_course(user.profile.group_name) or 1
        default_target = 10 if course == 1 else 20
        try:
            target = int(data.get("target_hours") or default_target)
        except (TypeError, ValueError):
            target = default_target
        target = max(1, target)
        goal, _ = VolunteerGoal.objects.get_or_create(
            volunteer=user, defaults={"target_hours": target}
        )
        goal.target_hours = target
        goal.current_hours = current_hours
        goal.completed = current_hours >= target
        goal.save()
        return JsonResponse(
            {
                "goal": {
                    "target_hours": goal.target_hours,
                    "current_hours": goal.current_hours,
                    "completed": goal.completed,
                    "progress_percentage": round(goal.get_progress_percentage(), 1),
                    "has_goal": True,
                }
            }
        )

    return JsonResponse({"message": "Method not allowed"}, status=405)


@csrf_exempt
@api_auth_required
def api_leaderboard(request):
    if request.method != "GET":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    volunteers = (
        User.objects.filter(profile__role="volunteer")
        .select_related("profile")
        .annotate(
            total_hours=Coalesce(
                Sum(
                    "requests__event__hours",
                    filter=Q(requests__status__in=["approved", "completed"]),
                ),
                0,
            )
        )
        .order_by("-total_hours", "username")
    )
    me_id = request.user.id
    data = []
    for idx, u in enumerate(volunteers, start=1):
        data.append(
            {
                "rank": idx,
                "id": u.id,
                "name": u.first_name or u.username,
                "group_name": u.profile.group_name if u.profile else None,
                "total_hours": u.total_hours,
                "is_me": u.id == me_id,
            }
        )
    return JsonResponse({"leaderboard": data})


@csrf_exempt
@api_auth_required
def api_review(request):
    if request.method != "POST":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"message": "Невірний формат запиту"}, status=400)
    request_id = data.get("request_id")
    rating = data.get("rating")
    comment = (data.get("comment") or "").strip()
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return JsonResponse({"message": "Вкажіть оцінку від 1 до 5"}, status=400)
    if rating < 1 or rating > 5:
        return JsonResponse({"message": "Оцінка має бути від 1 до 5"}, status=400)

    req = get_object_or_404(
        Request, id=request_id, Volunteer=request.user, status="completed"
    )
    review, created = VolunteerReview.objects.get_or_create(
        volunteer=request.user,
        event=req.event,
        defaults={"rating": rating, "comment": comment},
    )
    if not created:
        return JsonResponse({"message": "Відгук вже залишено"}, status=400)
    return JsonResponse(
        {
            "review": {
                "id": review.id,
                "rating": review.rating,
                "comment": review.comment,
            }
        }
    )


# ─── Chat API ─────────────────────────────────────────────────────────────────


@csrf_exempt
@api_auth_required
def api_chat_users(request):
    if request.method != "GET":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    me = request.user
    others = (
        User.objects.filter(
            Q(profile__role="volunteer")
            | Q(profile__role="organiser")
            | Q(profile__role="admin")
        )
        .exclude(id=me.id)
        .select_related("profile")
    )
    data = []
    for u in others:
        last = (
            Message.objects.filter(
                Q(sender=me, recipient=u) | Q(sender=u, recipient=me)
            )
            .order_by("-created_at")
            .first()
        )
        unread = Message.objects.filter(sender=u, recipient=me, is_read=False).count()
        data.append(
            {
                "id": u.id,
                "username": u.username,
                "name": u.first_name or u.username,
                "role": u.profile.role if hasattr(u, "profile") else "user",
                "last_message": (
                    {
                        "content": last.content,
                        "created_at": last.created_at.isoformat(),
                        "is_mine": last.sender_id == me.id,
                    }
                    if last
                    else None
                ),
                "unread_count": unread,
            }
        )
    data.sort(
        key=lambda x: x["last_message"]["created_at"] if x["last_message"] else "",
        reverse=True,
    )
    return JsonResponse({"users": data})


@csrf_exempt
@api_auth_required
def api_chat_messages(request, username):
    if request.method != "GET":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    me = request.user
    other = get_object_or_404(User, username=username)
    qs = Message.objects.filter(
        Q(sender=me, recipient=other) | Q(sender=other, recipient=me)
    ).order_by("created_at")
    data = [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": m.sender.first_name or m.sender.username,
            "recipient_id": m.recipient_id,
            "recipient_name": m.recipient.first_name or m.recipient.username,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "is_read": m.is_read,
            "is_mine": m.sender_id == me.id,
        }
        for m in qs
    ]
    Message.objects.filter(sender=other, recipient=me, is_read=False).update(
        is_read=True
    )
    return JsonResponse(
        {
            "messages": data,
            "other_user": {
                "id": other.id,
                "username": other.username,
                "name": other.first_name or other.username,
                "role": other.profile.role if hasattr(other, "profile") else "user",
            },
        }
    )


@csrf_exempt
@api_auth_required
def api_chat_send(request):
    if request.method != "POST":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"message": "Невірний формат запиту"}, status=400)
    recipient_username = data.get("recipient")
    content = (data.get("content") or "").strip()
    if not recipient_username or not content:
        return JsonResponse({"message": "Невірні дані"}, status=400)
    recipient = get_object_or_404(User, username=recipient_username)
    msg = Message.objects.create(
        sender=request.user, recipient=recipient, content=content
    )
    return JsonResponse(
        {
            "message": {
                "id": msg.id,
                "sender_id": msg.sender_id,
                "recipient_id": msg.recipient_id,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "is_read": msg.is_read,
                "is_mine": True,
            }
        }
    )


# ─── Purchase / Subscriptions API ────────────────────────────────────────────


@csrf_exempt
@api_auth_required
def api_purchase(request):
    if request.method != "POST":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"message": "Невірний формат запиту"}, status=400)
    plan_type = data.get("plan_type")
    if plan_type not in PLAN_PRICES:
        return JsonResponse({"message": "Невідомий тарифний план"}, status=400)

    card_number = (data.get("card_number") or "").replace(" ", "")
    cardholder = (data.get("cardholder") or "").strip()
    expiry = (data.get("expiry") or "").strip()
    cvv = (data.get("cvv") or "").strip()
    if not (
        len(card_number) >= 12
        and card_number.isdigit()
        and cardholder
        and len(expiry) >= 4
        and len(cvv) >= 3
        and cvv.isdigit()
    ):
        return JsonResponse({"message": "Невірні платіжні дані"}, status=400)

    if plan_type in ("analytics", "premium"):
        sub, _ = UserSubscription.objects.get_or_create(
            user=request.user,
            plan_type=plan_type,
            defaults={"is_active": True},
        )
        sub.is_active = True
        sub.save()
        return JsonResponse(
            {
                "subscription": {
                    "plan_type": plan_type,
                    "is_active": True,
                    "label": PLAN_LABELS[plan_type],
                    "price": PLAN_PRICES[plan_type],
                }
            }
        )

    if plan_type == "priority":
        project_id = data.get("project_id")
        if not project_id:
            return JsonResponse({"message": "Не вказано проєкт"}, status=400)
        project = get_object_or_404(Project, id=project_id)
        spot, _ = PrioritySpot.objects.get_or_create(
            volunteer=request.user, event=project
        )
        existing_req = Request.objects.filter(
            Volunteer=request.user, event=project
        ).first()
        if not existing_req:
            Request.objects.create(
                Volunteer=request.user, event=project, status="pending"
            )
        return JsonResponse(
            {
                "priority": {
                    "id": spot.id,
                    "project_id": project.id,
                    "project_name": project.name,
                    "label": PLAN_LABELS[plan_type],
                    "price": PLAN_PRICES[plan_type],
                }
            }
        )

    return JsonResponse({"message": "Невідомий тарифний план"}, status=400)


@csrf_exempt
@api_auth_required
def api_subscriptions(request):
    if request.method != "GET":
        return JsonResponse({"message": "Method not allowed"}, status=405)
    subs = list(
        UserSubscription.objects.filter(user=request.user, is_active=True).values_list(
            "plan_type", flat=True
        )
    )
    priority_event_ids = list(
        PrioritySpot.objects.filter(volunteer=request.user).values_list(
            "event_id", flat=True
        )
    )
    return JsonResponse(
        {
            "active_plans": subs,
            "has_premium": "premium" in subs,
            "has_analytics": "analytics" in subs or "premium" in subs,
            "priority_event_ids": priority_event_ids,
        }
    )


# ─── Web views: auth ──────────────────────────────────────────────────────────


def landing(request):
    return render(request, "volunteer_app/landing.html")


@csrf_exempt
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error_message = None
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        try:
            user_obj = User.objects.filter(
                Q(email__iexact=email) | Q(username__iexact=email)
            ).first()

            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password)

                if user is not None:
                    login(request, user)
                    return redirect("dashboard")
                else:
                    error_message = "Невірний пароль"
            else:
                error_message = "Користувача з таким email не знайдено"
        except User.MultipleObjectsReturned:
            error_message = "Виявлено декілька користувачів з цим email. Зверніться до адміністратора."

    return render(request, "volunteer_app/login.html", {"error": error_message})


# ─── Web views: dashboard ────────────────────────────────────────────────────


@login_required
def dashboard(request):
    user = request.user

    if request.method == "POST" and (
        user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")
    ):
        role = request.POST.get("role")
        full_name = request.POST.get("full_name")
        group_name = request.POST.get("group_name")
        email = request.POST.get("email")
        password = request.POST.get("password")

        if email and password:
            username = email.split("@")[0]
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            new_user = User.objects.create_user(
                username=username, email=email, password=password
            )
            if full_name:
                names = full_name.split(" ")
                new_user.first_name = names[0]
                if len(names) > 1:
                    new_user.last_name = " ".join(names[1:])
            new_user.save()

            profile, created = UserProfile.objects.get_or_create(user=new_user)
            if role == "organizer":
                role = "organiser"
            profile.role = (
                role if role in ["volunteer", "organiser", "admin"] else "volunteer"
            )
            if group_name:
                profile.group_name = group_name
            profile.save()
            messages.success(request, f"Користувача {email} успішно створено")
            return redirect("dashboard")

    try:
        if user.is_superuser:
            template, context = _admin_dashboard_ctx(user, request)
        elif hasattr(user, "profile"):
            role = user.profile.role
            if role == "volunteer":
                template, context = _volunteer_dashboard_ctx(user)
            elif role == "organiser":
                template, context = _organiser_dashboard_ctx(user)
            elif role == "admin":
                template, context = _admin_dashboard_ctx(user, request)
            else:
                template, context = "volunteer_app/landing.html", {}
        else:
            template, context = "volunteer_app/landing.html", {}
    except Exception as e:
        print(f"Error in dashboard: {e}")
        template, context = "volunteer_app/landing.html", {}

    return render(request, template, context)


# ─── Web views: projects ──────────────────────────────────────────────────────


@login_required
def apply_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user.profile.role == "volunteer":
        existing_request = Request.objects.filter(
            Volunteer=request.user, event=project
        ).first()
        if not existing_request:
            Request.objects.create(
                Volunteer=request.user, event=project, status="pending"
            )
            messages.success(request, f'Ви подали заявку на проєкт "{project.name}"')
        else:
            messages.info(request, "Ви вже подали заявку на цей проєкт")
    return redirect("dashboard")


@login_required
def manage_request(request, request_id, action):
    req = get_object_or_404(Request, id=request_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not (
        request.user.is_superuser
        or (
            hasattr(request.user, "profile")
            and request.user.profile.role in ["organiser", "admin"]
        )
    ):
        if is_ajax:
            return JsonResponse({"ok": False, "message": "Немає доступу"}, status=403)
        return redirect("dashboard")

    old_status = req.status
    msg = ""
    if action == "approve":
        req.status = "approved"
        msg = f"Заявку від {req.Volunteer.username} схвалено"
        if not is_ajax:
            messages.success(request, msg)
    elif action == "reject":
        req.status = "rejected"
        msg = f"Заявку від {req.Volunteer.username} відхилено"
        if not is_ajax:
            messages.success(request, msg)
    elif action == "complete":
        req.status = "completed"
        hours = request.POST.get("hours") or request.GET.get("hours")
        if hours:
            try:
                req.approved_hours = int(hours)
            except (ValueError, TypeError):
                req.approved_hours = req.event.hours
        else:
            req.approved_hours = req.event.hours
        msg = f"Волонтеру {req.Volunteer.username} зараховано {req.approved_hours} годин"
        if not is_ajax:
            messages.success(request, msg)

    req.save()
    project = req.event
    if action == "approve" and old_status != "approved" and project.max_volunteers > 0:
        Project.objects.filter(id=project.id).update(
            current_volunteers=F("current_volunteers") + 1
        )
    elif action == "reject" and old_status == "approved" and project.max_volunteers > 0:
        Project.objects.filter(id=project.id, current_volunteers__gt=0).update(
            current_volunteers=F("current_volunteers") - 1
        )

    if is_ajax:
        return JsonResponse({"ok": True, "message": msg, "approved_hours": req.approved_hours})
    return redirect("dashboard")


@login_required
def report_volunteer(request, request_id):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        report_text = request.POST.get("report", "").strip()
        req = get_object_or_404(Request, id=request_id)
        if request.user == req.event.organiser or request.user.is_superuser:
            if report_text:
                req.organizer_report = report_text
                req.organizer_reported = True
                req.save()
                msg = "Скаргу на волонтера відправлено адміну"
                if is_ajax:
                    return JsonResponse({"ok": True, "message": msg})
                messages.success(request, msg)
            else:
                msg = "Введіть текст скарги"
                if is_ajax:
                    return JsonResponse({"ok": False, "message": msg})
                messages.error(request, msg)
        else:
            msg = "У вас немає доступу"
            if is_ajax:
                return JsonResponse({"ok": False, "message": msg}, status=403)
            messages.error(request, msg)
    return redirect("dashboard")


@login_required
def toggle_star(request, request_id):
    req = get_object_or_404(Request, id=request_id)
    if request.user == req.event.organiser or request.user.is_superuser:
        req.star_rating = not req.star_rating
        req.save()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "starred": req.star_rating})
    return redirect("dashboard")


@login_required
def create_project(request):
    if request.method == "POST" and (
        request.user.is_superuser
        or (
            hasattr(request.user, "profile")
            and request.user.profile.role in ["organiser", "admin"]
        )
    ):
        post_data = request.POST.copy()
        date_val = post_data.get("date")
        if date_val and "T" not in date_val:
            post_data["date"] = f"{date_val}T12:00"
        if post_data.get("organization") == "":
            post_data["organization"] = None
        form = ProjectForm(post_data)
        if form.is_valid():
            project = form.save(commit=False)
            project.organiser = request.user
            project.save()
            messages.success(request, "Проєкт успішно створено")
        else:
            for error in form.errors.values():
                messages.error(request, error)
    return redirect("dashboard")


@login_required
def delete_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user == project.organiser or request.user.is_superuser:
        project.delete()
        messages.success(request, "Проєкт видалено")
    return redirect("dashboard")


# ─── Web views: auth / session ───────────────────────────────────────────────


def logout_view(request):
    logout(request)
    return redirect("landing")


# ─── Web views: profile / settings ───────────────────────────────────────────


@login_required
def profile_view(request):
    user = request.user
    context = {"user": user}
    if hasattr(user, "profile"):
        context["profile"] = user.profile

    if hasattr(user, "profile") and user.profile.role == "volunteer":
        context["total_events"] = Request.objects.filter(
            Volunteer=user, status__in=["approved", "completed"]
        ).count()
        context["total_hours"] = _calculate_volunteer_hours(user)

    return render(request, "volunteer_app/profile.html", context)


@login_required
def view_user_profile(request, username):
    viewed_user = get_object_or_404(User, username=username)

    if not (
        request.user.is_superuser
        or (
            hasattr(request.user, "profile")
            and request.user.profile.role in ["organiser", "admin"]
        )
    ):
        messages.error(request, "У вас немає доступу до цієї сторінки")
        return redirect("dashboard")

    context = {
        "viewed_user": viewed_user,
        "profile": viewed_user.profile if hasattr(viewed_user, "profile") else None,
    }

    if hasattr(viewed_user, "profile") and viewed_user.profile.role == "volunteer":
        context["total_events"] = Request.objects.filter(
            Volunteer=viewed_user, status="completed"
        ).count()
        context["total_hours"] = (
            Request.objects.filter(
                Volunteer=viewed_user, status="completed"
            ).aggregate(total=Sum("approved_hours"))["total"]
            or 0
        )
        context["user_requests"] = Request.objects.filter(
            Volunteer=viewed_user
        ).order_by("-date_requested")[:10]
        context["star_count"] = Request.objects.filter(
            Volunteer=viewed_user, star_rating=True
        ).count()

    return render(request, "volunteer_app/view_profile.html", context)


@login_required
def settings_view(request):
    user = request.user
    context = {"user": user}
    if hasattr(user, "profile"):
        context["profile"] = user.profile
    return render(request, "volunteer_app/settings.html", context)


@login_required
def update_profile(request):
    if request.method == "POST":
        user = request.user
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.save()

        if hasattr(user, "profile"):
            profile = user.profile
            group_name = request.POST.get("group_name", "").strip()
            if group_name:
                profile.group_name = group_name
            profile.save()

        messages.success(request, "Профіль оновлено")
    return redirect("settings")


@login_required
def update_password(request):
    if request.method == "POST":
        user = request.user
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        if new_password and new_password == confirm_password:
            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Пароль змінено")
        elif new_password != confirm_password:
            messages.error(request, "Паролі не співпадають")
        else:
            messages.error(request, "Введіть новий пароль")
    return redirect("settings")


# ─── Web views: admin tools ───────────────────────────────────────────────────


@login_required
def import_students(request):
    if not (
        request.user.is_superuser
        or (hasattr(request.user, "profile") and request.user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу до цієї сторінки")
        return redirect("dashboard")

    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Будь ласка, виберіть файл")
            return redirect("dashboard")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Файл повинен бути у форматі CSV")
            return redirect("dashboard")

        try:
            decoded_content = csv_file.read().decode("utf-8")
            lines = decoded_content.strip().split("\n")

            if len(lines) < 2:
                messages.error(request, "CSV файл порожній або не містить даних")
                return redirect("dashboard")

            imported_count = 0
            errors = []
            imported_students = []

            for i, line in enumerate(lines[1:], start=2):
                parts = line.strip().split(",")
                if len(parts) < 3:
                    errors.append(f"Рядок {i}: недостатньо даних")
                    continue

                full_name = parts[0].strip()
                group_name = parts[1].strip()
                email = parts[2].strip()
                password = parts[3].strip() if len(parts) > 3 else ""

                if not email:
                    errors.append(f"Рядок {i}: відсутній email")
                    continue

                if not full_name:
                    full_name = email.split("@")[0]

                username = email.split("@")[0]
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                if not password:
                    password = "".join(
                        random.choices(string.ascii_letters + string.digits, k=8)
                    )

                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": username,
                        "first_name": full_name.split()[0] if full_name else "",
                        "last_name": (
                            " ".join(full_name.split()[1:]) if full_name else ""
                        ),
                    },
                )

                if created:
                    user.set_password(password)
                    user.save()
                elif password:
                    user.set_password(password)
                    user.save()

                profile, profile_created = UserProfile.objects.get_or_create(user=user)
                profile.role = "volunteer"
                if group_name:
                    profile.group_name = group_name
                profile.save()

                imported_count += 1
                imported_students.append({"email": email, "password": password})

            if imported_count > 0:
                request.session["imported_students"] = imported_students
                messages.success(
                    request, f"Успішно імпортовано {imported_count} студентів"
                )
            if errors:
                for error in errors[:5]:
                    messages.warning(request, error)

        except Exception as e:
            messages.error(request, f"Помилка при обробці файлу: {str(e)}")

    return redirect("dashboard")


@login_required
def edit_user(request, username):
    if not (
        request.user.is_superuser
        or (hasattr(request.user, "profile") and request.user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    if request.method == "POST":
        user = get_object_or_404(User, username=username)

        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip()
        group_name = request.POST.get("group_name", "").strip()
        role = request.POST.get("role", "volunteer")
        new_password = request.POST.get("new_password", "").strip()

        if email:
            user.email = email

        if full_name:
            names = full_name.split(" ", 1)
            user.first_name = names[0]
            user.last_name = names[1] if len(names) > 1 else ""

        user.save()

        if hasattr(user, "profile"):
            profile = user.profile
            if role == "organizer":
                role = "organiser"
            profile.role = (
                role if role in ["volunteer", "organiser", "admin"] else "volunteer"
            )
            profile.group_name = group_name
            profile.save()

        if new_password:
            user.set_password(new_password)
            user.save()
            messages.success(request, f"Пароль для {user.username} змінено")

        messages.success(request, f"Користувача {user.username} оновлено")

    return redirect("dashboard")


@login_required
def delete_user(request, username):
    if not (
        request.user.is_superuser
        or (hasattr(request.user, "profile") and request.user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    try:
        user = get_object_or_404(User, username=username)
        if user.is_superuser:
            messages.error(request, "Неможливо видалити суперкористувача")
            return redirect("dashboard")

        user.delete()
        messages.success(request, f"Користувача {username} видалено")
    except Exception as e:
        messages.error(request, f"Помилка при видаленні: {str(e)}")

    return redirect("dashboard")


@login_required
def bulk_delete_users(request):
    if not (
        request.user.is_superuser
        or (hasattr(request.user, "profile") and request.user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    usernames = request.GET.get("usernames", "")
    if not usernames:
        messages.error(request, "Не вказано користувачів для видалення")
        return redirect("dashboard")

    username_list = [u.strip() for u in usernames.split(",") if u.strip()]
    deleted_count = 0

    for uname in username_list:
        try:
            user = User.objects.get(username=uname)
            if not user.is_superuser:
                user.delete()
                deleted_count += 1
        except User.DoesNotExist:
            pass

    messages.success(request, f"Видалено {deleted_count} користувачів")
    return redirect("dashboard")


# ─── Web views: chat ──────────────────────────────────────────────────────────


@login_required
def chat_view(request, username=None):
    user = request.user
    if not (
        hasattr(user, "profile")
        and user.profile.role in ["organiser", "admin", "volunteer"]
    ):
        messages.error(request, "У вас немає доступу до чату")
        return redirect("dashboard")

    context = {}
    if username:
        other_user = get_object_or_404(User, username=username)
        messages_list = Message.objects.filter(
            sender__in=[user, other_user], recipient__in=[user, other_user]
        ).order_by("created_at")
        context["chat_with"] = other_user
        context["messages"] = messages_list
        messages_list.filter(recipient=user).update(is_read=True)

    # Single query for user list + unread counts (avoids N+1)
    all_users = list(
        User.objects.filter(
            Q(profile__role="organiser")
            | Q(profile__role="admin")
            | Q(profile__role="volunteer")
        )
        .exclude(id=user.id)
        .select_related("profile")
        .annotate(
            unread_count=Count(
                "sent_messages",
                filter=Q(sent_messages__recipient=user, sent_messages__is_read=False),
            )
        )
    )

    # Single query for last messages (avoids N+1)
    other_ids = [u.id for u in all_users]
    recent_messages = (
        Message.objects.filter(
            Q(sender=user, recipient_id__in=other_ids)
            | Q(sender_id__in=other_ids, recipient=user)
        )
        .order_by("-created_at")
        .select_related("sender", "recipient")
    )
    last_message_map = {}
    for msg in recent_messages:
        other_id = msg.recipient_id if msg.sender_id == user.id else msg.sender_id
        if other_id not in last_message_map:
            last_message_map[other_id] = msg

    for u in all_users:
        u.last_message = last_message_map.get(u.id)

    context["all_users"] = all_users
    return render(request, "volunteer_app/chat.html", context)


@require_POST
@login_required
def send_message(request):
    recipient_username = request.POST.get("recipient")
    content = request.POST.get("content")

    if not recipient_username or not content:
        return JsonResponse({"error": "Invalid data"}, status=400)

    recipient = get_object_or_404(User, username=recipient_username)
    Message.objects.create(sender=request.user, recipient=recipient, content=content)

    return JsonResponse({"success": True})


# ─── Web views: archive / templates ──────────────────────────────────────────


@login_required
def archive_view(request):
    user = request.user
    if not (
        user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    archived_requests = ArchiveRequest.objects.all().order_by("-archived_at")
    return render(
        request, "volunteer_app/archive.html", {"archived_requests": archived_requests}
    )


@login_required
def templates_view(request):
    user = request.user
    if not (
        user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    context = {
        "group_templates": GroupTemplate.objects.all(),
        "event_templates": EventTemplate.objects.all(),
        "work_type_templates": WorkTypeTemplate.objects.all(),
        "hours_templates": HoursTemplate.objects.all(),
    }
    return render(request, "volunteer_app/templates.html", context)


@require_POST
@login_required
def create_template(request):
    template_type = request.POST.get("type")
    user = request.user
    if not (
        user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    if template_type == "group":
        name = request.POST.get("name")
        course = request.POST.get("course")
        if name and course:
            GroupTemplate.objects.create(name=name, course=course)
            messages.success(request, f"Групу {name} додано")

    elif template_type == "event":
        name = request.POST.get("name")
        location = request.POST.get("location")
        description = request.POST.get("description", "")
        default_hours = request.POST.get("default_hours")
        if name and location and default_hours:
            EventTemplate.objects.create(
                name=name,
                location=location,
                description=description,
                default_hours=default_hours,
            )
            messages.success(request, f"Шаблон заходу {name} додано")

    elif template_type == "work_type":
        name = request.POST.get("name")
        description = request.POST.get("description", "")
        if name:
            WorkTypeTemplate.objects.create(name=name, description=description)
            messages.success(request, f"Тип роботи {name} додано")

    elif template_type == "hours":
        name = request.POST.get("name")
        hours = request.POST.get("hours")
        description = request.POST.get("description", "")
        if name and hours:
            HoursTemplate.objects.create(name=name, hours=hours, description=description)
            messages.success(request, f"Шаблон годин {name} додано")

    return redirect("templates")


@require_POST
@login_required
def delete_template(request):
    template_type = request.POST.get("type")
    template_id = request.POST.get("id")
    user = request.user
    if not (
        user.is_superuser or (hasattr(user, "profile") and user.profile.role == "admin")
    ):
        messages.error(request, "У вас немає доступу")
        return redirect("dashboard")

    if template_type == "group":
        GroupTemplate.objects.get(id=template_id).delete()
    elif template_type == "event":
        EventTemplate.objects.get(id=template_id).delete()
    elif template_type == "work_type":
        WorkTypeTemplate.objects.get(id=template_id).delete()
    elif template_type == "hours":
        HoursTemplate.objects.get(id=template_id).delete()

    messages.success(request, "Шаблон видалено")
    return redirect("templates")


# ─── Web views: 2-factor password change ─────────────────────────────────────


def _mask_email(email):
    """Show only first 2 chars and domain: ab***@gmail.com"""
    try:
        local, domain = email.split("@", 1)
        return local[:2] + "***@" + domain
    except ValueError:
        return email


@login_required
def two_factor_password_change(request):
    user = request.user

    if request.method == "POST" and request.POST.get("step") == "verify":
        code_data = request.session.get("pwd_change_code")
        if not code_data:
            messages.error(request, "Сесія застаріла. Почніть знову.")
            return redirect("settings")

        if time.time() > code_data.get("expires", 0):
            request.session.pop("pwd_change_code", None)
            messages.error(request, "Код підтвердження застарів. Спробуйте знову.")
            return redirect("settings")

        code_data["attempts"] = code_data.get("attempts", 0) + 1
        request.session["pwd_change_code"] = code_data
        request.session.modified = True

        if code_data["attempts"] > 3:
            request.session.pop("pwd_change_code", None)
            messages.error(request, "Забагато невдалих спроб. Почніть знову.")
            return redirect("settings")

        entered = request.POST.get("code", "").strip()
        if entered != code_data["code"]:
            remaining = 3 - code_data["attempts"]
            messages.error(
                request,
                f"Невірний код підтвердження. Залишилось спроб: {remaining}.",
            )
            profile = getattr(user, "profile", None)
            return render(
                request,
                "volunteer_app/settings.html",
                {
                    "show_code_form": True,
                    "masked_email": _mask_email(code_data["email"]),
                    "profile": profile,
                },
            )

        new_password = code_data["new_password"]
        user.set_password(new_password)
        user.save()
        update_session_auth_hash(request, user)
        request.session.pop("pwd_change_code", None)
        messages.success(request, "✅ Пароль успішно змінено!")
        return redirect("settings")

    if request.method == "POST" and request.POST.get("step") == "send":
        email = request.POST.get("email", "").strip().lower()
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        if not user.email or email != user.email.strip().lower():
            messages.error(
                request,
                "❌ Введений email не збігається з email вашого акаунту.",
            )
            return redirect("settings")

        if not new_password or not confirm_password:
            messages.error(request, "Заповніть усі поля паролю.")
            return redirect("settings")

        if new_password != confirm_password:
            messages.error(request, "Нові паролі не співпадають.")
            return redirect("settings")

        if len(new_password) < 8:
            messages.error(request, "Пароль повинен містити мінімум 8 символів.")
            return redirect("settings")

        code = str(random.randint(100000, 999999))
        request.session["pwd_change_code"] = {
            "code": code,
            "email": email,
            "new_password": new_password,
            "expires": time.time() + 600,
            "attempts": 0,
        }
        request.session.modified = True

        sent = False
        try:
            send_mail(
                subject="BoscoVolunteer — Код підтвердження зміни пароля",
                message=(
                    f"Вітаємо, {user.get_full_name() or user.username}!\n\n"
                    f"Ваш код підтвердження для зміни пароля:\n\n"
                    f"  {code}\n\n"
                    f"Код дійсний 10 хвилин.\n"
                    f"Якщо ви не ініціювали цей запит — проігноруйте цей лист."
                ),
                from_email="BoscoVolunteer <noreply@boscovolunteer.com>",
                recipient_list=[email],
                fail_silently=False,
            )
            sent = True
        except Exception:
            pass

        if sent:
            messages.info(
                request,
                f"📧 Код підтвердження надіслано на {_mask_email(email)}",
            )
        else:
            messages.warning(request, f"[DEV] SMTP не налаштовано. Ваш код: {code}")

        profile = getattr(user, "profile", None)
        return render(
            request,
            "volunteer_app/settings.html",
            {
                "show_code_form": True,
                "masked_email": _mask_email(email),
                "profile": profile,
            },
        )

    return redirect("settings")


# ─── Web views: events / goals ────────────────────────────────────────────────


@login_required
def events_page(request):
    projects = Project.objects.all().order_by("-date")
    return render(request, "volunteer_app/events.html", {"projects": projects})


@login_required
def create_volunteer_goal(request):
    if request.method == "POST":
        user = request.user
        if not (hasattr(user, "profile") and user.profile.role == "volunteer"):
            messages.error(request, "Тільки волонтери можуть створювати ціль")
            return redirect("dashboard")

        course = extract_course(user.profile.group_name)
        target_hours = 10 if course == 1 else (20 if course and course >= 2 else 10)

        goal, created = VolunteerGoal.objects.get_or_create(
            volunteer=user, defaults={"target_hours": target_hours}
        )
        if not created:
            goal.target_hours = target_hours
            goal.save()

        messages.success(request, f"Ціль встановлено: {target_hours} годин")
        return redirect("dashboard")

    return redirect("dashboard")


# ─── Web views: payment / subscriptions ──────────────────────────────────────


@login_required
def purchase_plan(request, plan_type):
    if plan_type not in PLAN_PRICES:
        messages.error(request, "Невідомий тарифний план")
        return redirect("dashboard")

    price = PLAN_PRICES[plan_type]
    label = PLAN_LABELS[plan_type]
    project_id = request.GET.get("project_id") or request.POST.get("project_id")

    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            if plan_type in ("analytics", "premium"):
                UserSubscription.objects.get_or_create(
                    user=request.user,
                    plan_type=plan_type,
                    defaults={"is_active": True},
                )
                messages.success(request, f"Підписку «{label}» успішно активовано!")
            elif plan_type == "priority" and project_id:
                project = get_object_or_404(Project, id=project_id)
                PrioritySpot.objects.get_or_create(
                    volunteer=request.user, event=project
                )
                existing_req = Request.objects.filter(
                    Volunteer=request.user, event=project
                ).first()
                if not existing_req:
                    Request.objects.create(
                        Volunteer=request.user, event=project, status="pending"
                    )
                messages.success(
                    request,
                    f"Пріоритетне місце на «{project.name}» придбано! Заявку подано.",
                )
                return redirect("dashboard")
            return redirect("dashboard")
    else:
        form = PaymentForm()

    return render(
        request,
        "volunteer_app/payment.html",
        {
            "form": form,
            "plan_type": plan_type,
            "plan_label": label,
            "price": price,
            "project_id": project_id,
        },
    )


# ─── Web views: analytics ─────────────────────────────────────────────────────


@login_required
def analytics_dashboard(request):
    user = request.user
    if not (hasattr(user, "profile") and user.profile.role in ["organiser", "admin"]):
        messages.error(request, "Доступ заборонено")
        return redirect("dashboard")

    has_access = (
        user.is_superuser
        or (hasattr(user, "profile") and user.profile.role == "admin")
        or UserSubscription.objects.filter(
            user=user, plan_type__in=["analytics", "premium"], is_active=True
        ).exists()
    )
    if not has_access:
        messages.warning(request, "Для доступу до аналітики придбайте підписку")
        return redirect("purchase_plan", plan_type="analytics")

    if hasattr(user, "profile") and user.profile.role == "organiser":
        projects = Project.objects.filter(organiser=user)
    else:
        projects = Project.objects.all()

    # Single query instead of N*5 queries via annotate
    project_stats_qs = projects.annotate(
        req_total=Count("requests", distinct=True),
        req_approved=Count(
            "requests", filter=Q(requests__status="approved"), distinct=True
        ),
        req_completed=Count(
            "requests", filter=Q(requests__status="completed"), distinct=True
        ),
        req_stars=Count(
            "requests", filter=Q(requests__star_rating=True), distinct=True
        ),
        avg_rating=Avg("reviews__rating"),
        reviews_count=Count("reviews", distinct=True),
    )

    project_stats = [
        {
            "project": p,
            "total": p.req_total,
            "approved": p.req_approved,
            "completed": p.req_completed,
            "stars": p.req_stars,
            "avg_rating": round(p.avg_rating, 1) if p.avg_rating else None,
            "reviews_count": p.reviews_count,
        }
        for p in project_stats_qs
    ]

    labels = [s["project"].name[:20] for s in project_stats]
    approved_data = [s["approved"] for s in project_stats]
    completed_data = [s["completed"] for s in project_stats]
    ratings_data = [float(s["avg_rating"]) if s["avg_rating"] else 0 for s in project_stats]

    # Rating distribution: 1 query instead of 5
    rating_dist_qs = (
        VolunteerReview.objects.filter(event__in=projects)
        .values("rating")
        .annotate(cnt=Count("id"))
    )
    rating_dist_map = {item["rating"]: item["cnt"] for item in rating_dist_qs}
    rating_dist = [rating_dist_map.get(i, 0) for i in range(1, 6)]

    context = {
        "project_stats": project_stats,
        "chart_labels": json.dumps(labels, ensure_ascii=False),
        "chart_approved": json.dumps(approved_data),
        "chart_completed": json.dumps(completed_data),
        "chart_ratings": json.dumps(ratings_data),
        "chart_rating_dist": json.dumps(rating_dist),
        "total_projects": projects.count(),
        "total_volunteers": Request.objects.filter(
            event__in=projects, status__in=["approved", "completed"]
        )
        .values("Volunteer")
        .distinct()
        .count(),
        "total_reviews": VolunteerReview.objects.filter(event__in=projects).count(),
    }
    return render(request, "volunteer_app/analytics.html", context)


# ─── Web views: reviews ───────────────────────────────────────────────────────


@login_required
def leave_review(request, request_id):
    req = get_object_or_404(
        Request, id=request_id, Volunteer=request.user, status="completed"
    )

    if VolunteerReview.objects.filter(volunteer=request.user, event=req.event).exists():
        messages.info(request, "Ви вже залишили відгук про цей захід")
        return redirect("dashboard")

    if request.method == "POST":
        form = VolunteerReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.volunteer = request.user
            review.event = req.event
            review.save()
            messages.success(request, f"Дякуємо за відгук про «{req.event.name}»!")
            return redirect("dashboard")
    else:
        form = VolunteerReviewForm()

    return render(
        request,
        "volunteer_app/leave_review.html",
        {
            "form": form,
            "event": req.event,
            "request_obj": req,
        },
    )


# ─── Web views: organizations ─────────────────────────────────────────────────


@login_required
def organization_list(request):
    organizations = Organization.objects.all().order_by("name")
    user_orgs = organizations.filter(owner=request.user)
    form = OrganizationForm()
    return render(
        request,
        "volunteer_app/organizations.html",
        {
            "organizations": organizations,
            "user_orgs": user_orgs,
            "form": form,
        },
    )


@login_required
def create_organization(request):
    if request.method == "POST":
        form = OrganizationForm(request.POST)
        if form.is_valid():
            org = form.save(commit=False)
            org.owner = request.user
            form.save(commit=False)
            org.save()
            messages.success(request, f"Організацію «{org.name}» створено!")
            return redirect("organization_list")
        else:
            messages.error(request, "Помилка при створенні організації")
    return redirect("organization_list")


@login_required
def organization_detail(request, org_slug):
    org = get_object_or_404(Organization, slug=org_slug)
    projects = Project.objects.filter(organization=org).order_by("-date")
    return render(
        request,
        "volunteer_app/organization_detail.html",
        {
            "org": org,
            "projects": projects,
        },
    )
