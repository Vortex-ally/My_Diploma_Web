"""Regression tests for object-level authorization on volunteer Request management.

Covers the IDOR fix in manage_request() (web) and its JSON API analog
api_project_applications() PUT, so the two entry points cannot diverge again.
"""

import json
from html.parser import HTMLParser

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Project, Request


def _set_role(user, role):
    user.profile.role = role
    user.profile.save()


class _ScriptTagAuditor(HTMLParser):
    """Mirrors a browser's raw-text content model for <script> elements:
    per the HTML5 spec (and Python's stdlib parser), everything between a
    <script ...> start tag and the first literal `</script>` is CDATA --
    no nested tags are recognized inside it. This lets us assert the real
    security property: untrusted data embedded via `json_script` cannot
    prematurely close its <script type="application/json"> element and
    make the parser see a *new* <script> start tag (i.e. a script-breakout
    XSS), rather than just grepping for a specific payload substring.
    """

    def __init__(self):
        super().__init__()
        self.script_open_count = 0
        self.script_texts = {}
        self._capturing_id = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script_open_count += 1
            elem_id = dict(attrs).get("id")
            if elem_id:
                self._capturing_id = elem_id
                self._buffer = []

    def handle_data(self, data):
        if self._capturing_id is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._capturing_id is not None:
            self.script_texts[self._capturing_id] = "".join(self._buffer)
            self._capturing_id = None


def _audit_scripts(html_content):
    parser = _ScriptTagAuditor()
    parser.feed(html_content)
    parser.close()
    return parser


# analytics.html has exactly 2 literal <script> tags in the static markup
# (the Chart.js CDN <script src=...> and the final inline chart-setup
# <script>), plus 5 <script type="application/json"> blocks emitted by the
# `json_script` filter -- regardless of what any Project.name contains.
EXPECTED_ANALYTICS_SCRIPT_TAG_COUNT = 7


class ManageRequestAuthorizationTests(TestCase):
    """manage_request() must only let the owning organiser or an admin act."""

    def setUp(self):
        self.organiser_a = User.objects.create_user(
            username="organiser_a", password="pass12345"
        )
        _set_role(self.organiser_a, "organiser")

        self.organiser_b = User.objects.create_user(
            username="organiser_b", password="pass12345"
        )
        _set_role(self.organiser_b, "organiser")

        self.admin = User.objects.create_user(
            username="admin_user", password="pass12345"
        )
        _set_role(self.admin, "admin")

        self.volunteer = User.objects.create_user(
            username="volunteer_user", password="pass12345"
        )
        _set_role(self.volunteer, "volunteer")

        self.project_a = Project.objects.create(
            name="Project A",
            organiser=self.organiser_a,
            date=timezone.now(),
            hours=5,
            max_volunteers=1,
        )
        self.project_b = Project.objects.create(
            name="Project B",
            organiser=self.organiser_b,
            date=timezone.now(),
            hours=5,
        )
        self.request_a = Request.objects.create(
            Volunteer=self.volunteer, event=self.project_a, status="pending"
        )

    def _post(self, username, action, **extra):
        self.client.login(username=username, password="pass12345")
        return self.client.post(
            reverse("manage_request", args=[self.request_a.id, action]), **extra
        )

    # ---- CASE 1: organiser B (foreign project) is denied ----
    def test_case1_foreign_organiser_denied_ajax(self):
        response = self._post(
            "organiser_b", "approve", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")

    def test_case1_foreign_organiser_denied_non_ajax_status_unchanged(self):
        response = self._post("organiser_b", "approve")
        self.assertEqual(response.status_code, 302)  # always redirects to dashboard
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")  # but nothing changed

    # ---- CASE 2: owning organiser succeeds ----
    def test_case2_owning_organiser_can_approve(self):
        response = self._post(
            "organiser_a", "approve", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "approved")

    # ---- CASE 3: admin/superuser can manage any request ----
    def test_case3_admin_can_approve_foreign_request(self):
        response = self._post(
            "admin_user", "approve", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "approved")

    def test_case3_superuser_can_approve_foreign_request(self):
        User.objects.create_superuser(
            username="root", email="root@example.com", password="pass12345"
        )
        response = self._post("root", "approve", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "approved")

    # ---- CASE 4: volunteer is denied ----
    def test_case4_volunteer_denied(self):
        response = self._post(
            "volunteer_user", "approve", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")

    # ---- CASE 5: cannot bypass via id/action manipulation ----
    def test_case5_foreign_organiser_cannot_bypass_via_any_action(self):
        for action in ["approve", "reject", "complete"]:
            response = self._post(
                "organiser_b", action, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )
            self.assertEqual(response.status_code, 403)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")

    # ---- Regression: existing approve/reject/complete/hours logic still works ----
    def test_reject_by_owner_still_works(self):
        response = self._post(
            "organiser_a", "reject", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "rejected")

    def test_complete_sets_approved_hours(self):
        self.request_a.status = "approved"
        self.request_a.save()
        self.client.login(username="organiser_a", password="pass12345")
        response = self.client.post(
            reverse("manage_request", args=[self.request_a.id, "complete"]),
            {"hours": "7"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "completed")
        self.assertEqual(self.request_a.approved_hours, 7)

    def test_approve_increments_current_volunteers_when_capped(self):
        self.assertEqual(self.project_a.current_volunteers, 0)
        self._post("organiser_a", "approve", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.project_a.refresh_from_db()
        self.assertEqual(self.project_a.current_volunteers, 1)

    def test_reject_after_approve_decrements_current_volunteers(self):
        self.request_a.status = "approved"
        self.request_a.save()
        Project.objects.filter(id=self.project_a.id).update(current_volunteers=1)
        self._post("organiser_a", "reject", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.project_a.refresh_from_db()
        self.assertEqual(self.project_a.current_volunteers, 0)


class ApiProjectApplicationsAuthorizationTests(TestCase):
    """Same authorization rule, JSON API analog: api_project_applications() PUT."""

    def setUp(self):
        self.organiser_a = User.objects.create_user(
            username="api_organiser_a", password="pass12345"
        )
        _set_role(self.organiser_a, "organiser")

        self.organiser_b = User.objects.create_user(
            username="api_organiser_b", password="pass12345"
        )
        _set_role(self.organiser_b, "organiser")

        self.admin = User.objects.create_user(
            username="api_admin", password="pass12345"
        )
        _set_role(self.admin, "admin")

        self.volunteer = User.objects.create_user(
            username="api_volunteer", password="pass12345"
        )
        _set_role(self.volunteer, "volunteer")

        self.project_a = Project.objects.create(
            name="API Project A",
            organiser=self.organiser_a,
            date=timezone.now(),
            hours=5,
        )
        self.project_b = Project.objects.create(
            name="API Project B",
            organiser=self.organiser_b,
            date=timezone.now(),
            hours=5,
        )
        self.request_a = Request.objects.create(
            Volunteer=self.volunteer, event=self.project_a, status="pending"
        )

    def _put(self, username, project, application_id, action="approve"):
        self.client.login(username=username, password="pass12345")
        return self.client.put(
            reverse("api_project_applications", args=[project.id]),
            data=json.dumps({"application_id": application_id, "action": action}),
            content_type="application/json",
        )

    def test_confused_deputy_own_project_url_foreign_application_id_denied(self):
        """organiser_b's own project_id in the URL, but application_id belongs
        to organiser_a's project -- must be rejected (previously not checked)."""
        response = self._put("api_organiser_b", self.project_b, self.request_a.id)
        self.assertEqual(response.status_code, 400)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")

    def test_foreign_organiser_denied(self):
        response = self._put("api_organiser_b", self.project_a, self.request_a.id)
        self.assertEqual(response.status_code, 403)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")

    def test_owning_organiser_can_approve(self):
        response = self._put("api_organiser_a", self.project_a, self.request_a.id)
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "approved")

    def test_admin_can_approve_foreign_request(self):
        response = self._put("api_admin", self.project_a, self.request_a.id)
        self.assertEqual(response.status_code, 200)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "approved")

    def test_volunteer_denied(self):
        response = self._put("api_volunteer", self.project_a, self.request_a.id)
        self.assertEqual(response.status_code, 403)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, "pending")


class ApiProjectApplicationsGetAuthorizationTests(TestCase):
    """P0 #2: api_project_applications() GET must not leak applicant PII
    (name/email) to anyone other than the owning organiser, admin, or
    superuser. Anonymous and unrelated users must be denied."""

    def setUp(self):
        self.organiser_a = User.objects.create_user(
            username="get_organiser_a", password="pass12345"
        )
        _set_role(self.organiser_a, "organiser")

        self.organiser_b = User.objects.create_user(
            username="get_organiser_b", password="pass12345"
        )
        _set_role(self.organiser_b, "organiser")

        self.admin = User.objects.create_user(
            username="get_admin", password="pass12345"
        )
        _set_role(self.admin, "admin")

        self.superuser = User.objects.create_superuser(
            username="get_root", email="root@example.com", password="pass12345"
        )

        self.volunteer = User.objects.create_user(
            username="get_volunteer", password="pass12345"
        )
        _set_role(self.volunteer, "volunteer")

        self.project_a = Project.objects.create(
            name="Get Project A",
            organiser=self.organiser_a,
            date=timezone.now(),
            hours=5,
        )
        self.project_b = Project.objects.create(
            name="Get Project B",
            organiser=self.organiser_b,
            date=timezone.now(),
            hours=5,
        )
        self.applicant = User.objects.create_user(
            username="get_applicant", email="applicant@college.edu", password="x"
        )
        self.request_a = Request.objects.create(
            Volunteer=self.applicant, event=self.project_a, status="pending"
        )

    def _get(self, username, project):
        if username is not None:
            self.client.login(username=username, password="pass12345")
        return self.client.get(reverse("api_project_applications", args=[project.id]))

    # ---- CASE 1: anonymous -> denied, no data ----
    def test_case1_anonymous_denied(self):
        response = self._get(None, self.project_a)
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn("applications", response.json())

    # ---- CASE 2: volunteer (not organiser/admin) -> denied ----
    def test_case2_volunteer_denied(self):
        response = self._get("get_volunteer", self.project_a)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("applications", response.json())

    # ---- CASE 3: owning organiser -> success ----
    def test_case3_owning_organiser_can_view(self):
        response = self._get("get_organiser_a", self.project_a)
        self.assertEqual(response.status_code, 200)
        self.assertIn("applications", response.json())

    # ---- CASE 4: foreign organiser -> denied ----
    def test_case4_foreign_organiser_denied(self):
        response = self._get("get_organiser_b", self.project_a)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("applications", response.json())

    # ---- CASE 5: admin -> success ----
    def test_case5_admin_can_view(self):
        response = self._get("get_admin", self.project_a)
        self.assertEqual(response.status_code, 200)
        self.assertIn("applications", response.json())

    # ---- CASE 6: superuser -> success ----
    def test_case6_superuser_can_view(self):
        response = self._get("get_root", self.project_a)
        self.assertEqual(response.status_code, 200)
        self.assertIn("applications", response.json())

    # ---- CASE 7: switching project_id does not leak a foreign project ----
    def test_case7_switching_project_id_does_not_bypass(self):
        self.client.login(username="get_organiser_b", password="pass12345")
        # organiser_b can read their own project...
        own = self.client.get(
            reverse("api_project_applications", args=[self.project_b.id])
        )
        self.assertEqual(own.status_code, 200)
        # ...but not project A merely by changing the id in the URL.
        foreign = self.client.get(
            reverse("api_project_applications", args=[self.project_a.id])
        )
        self.assertEqual(foreign.status_code, 403)
        self.assertNotIn("applications", foreign.json())

    # ---- CASE 8: successful response exposes only the fields the endpoint
    # needs, and denied responses expose no applicant data at all ----
    def test_case8_success_response_shape_is_unchanged_and_minimal(self):
        response = self._get("get_organiser_a", self.project_a)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["applications"]), 1)
        app = body["applications"][0]
        self.assertEqual(
            set(app.keys()),
            {"id", "user_id", "user_name", "user_email", "status", "date"},
        )
        self.assertEqual(app["user_email"], "applicant@college.edu")

    def test_case8_denied_response_contains_no_applicant_data(self):
        response = self._get("get_volunteer", self.project_a)
        body = response.json()
        self.assertNotIn("applicant@college.edu", response.content.decode())
        self.assertEqual(set(body.keys()), {"message"})


class AnalyticsChartXssTests(TestCase):
    """P0 #3: Project.name (fully user-controlled) must not be able to break
    out of the json_script <script type="application/json"> element and get
    the browser to open a new, executable <script> element in analytics.html.

    We don't just grep the response for a specific payload substring -- we
    parse the returned HTML the way a browser's HTML5 tokenizer would (see
    _ScriptTagAuditor) and assert the actual security invariant: the number
    of <script> elements the parser sees never changes, no matter what a
    Project.name contains, and each dataset still round-trips through
    JSON.parse() to the exact original value.
    """

    def setUp(self):
        self.organiser = User.objects.create_user(
            username="xss_organiser", password="pass12345"
        )
        _set_role(self.organiser, "organiser")

        self.admin = User.objects.create_user(
            username="xss_admin", password="pass12345"
        )
        _set_role(self.admin, "admin")

    def _get_analytics_html(self):
        self.client.login(username="xss_admin", password="pass12345")
        response = self.client.get(reverse("analytics"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _make_project(self, name):
        return Project.objects.create(
            name=name, organiser=self.organiser, date=timezone.now(), hours=1
        )

    # ---- CASE 1: classic script-breakout payload ----
    def test_case1_script_breakout_creates_no_new_script_element(self):
        # analytics_dashboard() truncates chart labels to 20 chars -- that's
        # pre-existing business logic, unrelated to this security fix, so
        # the assertion below expects the same truncated value.
        payload = "</script><script>alert(1)</script>"
        self._make_project(payload)

        html = self._get_analytics_html()
        audit = _audit_scripts(html)

        # The core security invariant: no extra <script> start tag appeared.
        self.assertEqual(audit.script_open_count, EXPECTED_ANALYTICS_SCRIPT_TAG_COUNT)
        # The payload must still be there, but only as inert JSON text.
        labels = json.loads(audit.script_texts["chart-labels-data"])
        self.assertIn(payload[:20], labels)

    # ---- CASE 2: full set of dangerous HTML/JS characters ----
    def test_case2_dangerous_characters_cannot_close_json_script_or_execute(self):
        payload = "<script>alert(1)</script>\"'&/<img src=x onerror=alert(2)>"
        self._make_project(payload)

        html = self._get_analytics_html()
        audit = _audit_scripts(html)

        self.assertEqual(audit.script_open_count, EXPECTED_ANALYTICS_SCRIPT_TAG_COUNT)
        labels = json.loads(audit.script_texts["chart-labels-data"])
        self.assertIn(payload[:20], labels)

    # ---- CASE 3: exact data preservation through JSON.parse() ----
    def test_case3_original_name_recovered_exactly(self):
        name = '<>&"\'/weird "quoted" & <b>bold</b>/slash'
        self._make_project(name)

        html = self._get_analytics_html()
        audit = _audit_scripts(html)
        labels = json.loads(audit.script_texts["chart-labels-data"])

        # Compare against the same truncation the view applies to every
        # chart label (pre-existing business logic, not part of this fix) --
        # this proves round-trip fidelity for every character up to that cap.
        self.assertIn(name[:20], labels)

    # ---- CASE 4: normal data / numeric datasets unchanged after switching
    # from manual json.dumps()+|safe to json_script ----
    def test_case4_normal_project_and_numeric_datasets_unchanged(self):
        self._make_project("Прибирання парку")

        html = self._get_analytics_html()
        audit = _audit_scripts(html)

        labels = json.loads(audit.script_texts["chart-labels-data"])
        approved = json.loads(audit.script_texts["chart-approved-data"])
        self.assertIn("Прибирання парку", labels)
        self.assertEqual(approved, [0])

    # ---- CASE 5: all 5 datasets present, with correct values ----
    def test_case5_all_five_datasets_present_and_correct(self):
        project = self._make_project("Захід")
        volunteer = User.objects.create_user(username="xss_volunteer", password="x")
        Request.objects.create(
            Volunteer=volunteer, event=project, status="approved", approved_hours=4
        )

        html = self._get_analytics_html()
        audit = _audit_scripts(html)

        for elem_id in (
            "chart-labels-data",
            "chart-approved-data",
            "chart-completed-data",
            "chart-ratings-data",
            "chart-rating-dist-data",
        ):
            self.assertIn(elem_id, audit.script_texts)

        self.assertEqual(json.loads(audit.script_texts["chart-labels-data"]), ["Захід"])
        self.assertEqual(json.loads(audit.script_texts["chart-approved-data"]), [1])
        self.assertEqual(json.loads(audit.script_texts["chart-completed-data"]), [0])
        self.assertEqual(
            json.loads(audit.script_texts["chart-rating-dist-data"]), [0, 0, 0, 0, 0]
        )


class LoginCsrfProtectionTests(TestCase):
    """P0 #4: login_view() must be protected by Django's normal CSRF check,
    like every other state-changing view in this project.

    A cross-site attack here doesn't need JavaScript or CORS approval: a
    plain auto-submitting `<form method="post" action=".../login/">` is a
    CORS "simple request", so the only thing standing between an attacker's
    page and establishing a session in the victim's browser is Django's own
    CSRF check. We use Client(enforce_csrf_checks=True) because the default
    test Client silently *disables* CSRF checking for convenience, which
    would hide exactly this vulnerability. We assert the real security
    property -- whether an authenticated session got established -- not
    just the HTTP status code.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="csrf_victim", email="victim@example.com", password="pass12345"
        )

    @staticmethod
    def _session_established(client):
        return client.session.get("_auth_user_id") is not None

    # ---- CASE 1: cross-site-like POST, zero CSRF token -> must be denied,
    # and critically, no session may be established ----
    def test_case1_login_without_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            reverse("login"),
            {"email": "csrf_victim", "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self._session_established(client))

    # ---- CASE 2: legitimate flow -- real GET, real token -- must still work ----
    def test_case2_login_with_valid_csrf_token_succeeds(self):
        client = Client(enforce_csrf_checks=True)

        get_response = client.get(reverse("login"))
        self.assertEqual(get_response.status_code, 200)
        token = get_response.cookies["csrftoken"].value

        response = client.post(
            reverse("login"),
            {
                "email": "csrf_victim",
                "password": "pass12345",
                "csrfmiddlewaretoken": token,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("dashboard"))
        # The session must belong to the exact user who logged in -- not
        # merely "some" session.
        self.assertEqual(str(client.session.get("_auth_user_id")), str(self.user.pk))

    # ---- CASE 3: a token is present but doesn't match this client's CSRF
    # cookie (stolen/forged/foreign token) -> must be denied, no session ----
    def test_case3_login_with_mismatched_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)

        get_response = client.get(reverse("login"))
        real_token = get_response.cookies["csrftoken"].value
        bogus_token = real_token[:-1] + ("0" if real_token[-1] != "0" else "1")

        response = client.post(
            reverse("login"),
            {
                "email": "csrf_victim",
                "password": "pass12345",
                "csrfmiddlewaretoken": bogus_token,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self._session_established(client))


class VolunteerCapacityEnforcementTests(TestCase):
    """P0 #5: for any Project with max_volunteers > 0, the number of
    approved Requests must never exceed max_volunteers, and a Request may
    become "approved" only if a slot was actually, atomically reserved.
    We check both Request.status and Project.current_volunteers together --
    a passing test must never accept a state where one moved and the other
    didn't. Both entry points (web manage_request() and the JSON API
    api_project_applications() PUT) are exercised, since they must agree.
    """

    def setUp(self):
        self.organiser = User.objects.create_user(
            username="cap_organiser", password="pass12345"
        )
        _set_role(self.organiser, "organiser")

    def _make_project(self, max_volunteers):
        return Project.objects.create(
            name="Capacity Test Event",
            organiser=self.organiser,
            date=timezone.now(),
            hours=2,
            max_volunteers=max_volunteers,
        )

    def _make_pending_request(self, project, username):
        volunteer = User.objects.create_user(username=username, password="x")
        _set_role(volunteer, "volunteer")
        return Request.objects.create(
            Volunteer=volunteer, event=project, status="pending"
        )

    def _approve_web(self, req):
        self.client.login(username="cap_organiser", password="pass12345")
        return self.client.post(
            reverse("manage_request", args=[req.id, "approve"]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def _reject_web(self, req):
        self.client.login(username="cap_organiser", password="pass12345")
        return self.client.post(
            reverse("manage_request", args=[req.id, "reject"]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def _approve_api(self, project, req):
        self.client.login(username="cap_organiser", password="pass12345")
        return self.client.put(
            reverse("api_project_applications", args=[project.id]),
            data=json.dumps({"application_id": req.id, "action": "approve"}),
            content_type="application/json",
        )

    def _reject_api(self, project, req):
        self.client.login(username="cap_organiser", password="pass12345")
        return self.client.put(
            reverse("api_project_applications", args=[project.id]),
            data=json.dumps({"application_id": req.id, "action": "reject"}),
            content_type="application/json",
        )

    # ---- CASE 1: capacity boundary -- the core regression for P0 #5 ----
    def test_case1_capacity_boundary_web(self):
        project = self._make_project(max_volunteers=1)
        req1 = self._make_pending_request(project, "cap_vol_web_1")
        req2 = self._make_pending_request(project, "cap_vol_web_2")

        resp1 = self._approve_web(req1)
        self.assertEqual(resp1.status_code, 200)
        req1.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req1.status, "approved")
        self.assertEqual(project.current_volunteers, 1)

        resp2 = self._approve_web(req2)
        self.assertEqual(resp2.status_code, 400)
        req2.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req2.status, "pending")
        self.assertEqual(project.current_volunteers, 1)
        self.assertEqual(
            Request.objects.filter(event=project, status="approved").count(), 1
        )
        self.assertEqual(project.max_volunteers, 1)

    def test_case1_capacity_boundary_api(self):
        project = self._make_project(max_volunteers=1)
        req1 = self._make_pending_request(project, "cap_vol_api_1")
        req2 = self._make_pending_request(project, "cap_vol_api_2")

        resp1 = self._approve_api(project, req1)
        self.assertEqual(resp1.status_code, 200)
        req1.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req1.status, "approved")
        self.assertEqual(project.current_volunteers, 1)

        resp2 = self._approve_api(project, req2)
        self.assertEqual(resp2.status_code, 400)
        req2.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req2.status, "pending")
        self.assertEqual(project.current_volunteers, 1)
        self.assertEqual(
            Request.objects.filter(event=project, status="approved").count(), 1
        )

    # ---- CASE 2: exact capacity succeeds ----
    def test_case2_exact_capacity_succeeds_web(self):
        project = self._make_project(max_volunteers=2)
        req1 = self._make_pending_request(project, "cap2_vol_web_1")
        req2 = self._make_pending_request(project, "cap2_vol_web_2")

        self.assertEqual(self._approve_web(req1).status_code, 200)
        self.assertEqual(self._approve_web(req2).status_code, 200)

        req1.refresh_from_db()
        req2.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req1.status, "approved")
        self.assertEqual(req2.status, "approved")
        self.assertEqual(project.current_volunteers, 2)
        self.assertLessEqual(project.current_volunteers, project.max_volunteers)

    def test_case2_exact_capacity_succeeds_api(self):
        project = self._make_project(max_volunteers=2)
        req1 = self._make_pending_request(project, "cap2_vol_api_1")
        req2 = self._make_pending_request(project, "cap2_vol_api_2")

        self.assertEqual(self._approve_api(project, req1).status_code, 200)
        self.assertEqual(self._approve_api(project, req2).status_code, 200)

        req1.refresh_from_db()
        req2.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req1.status, "approved")
        self.assertEqual(req2.status, "approved")
        self.assertEqual(project.current_volunteers, 2)
        self.assertLessEqual(project.current_volunteers, project.max_volunteers)

    # ---- CASE 3: unlimited (max_volunteers == 0) semantics preserved ----
    def test_case3_unlimited_project_web(self):
        project = self._make_project(max_volunteers=0)
        reqs = [
            self._make_pending_request(project, f"cap0_vol_web_{i}") for i in range(5)
        ]

        for r in reqs:
            self.assertEqual(self._approve_web(r).status_code, 200)

        for r in reqs:
            r.refresh_from_db()
            self.assertEqual(r.status, "approved")

    def test_case3_unlimited_project_api(self):
        project = self._make_project(max_volunteers=0)
        reqs = [
            self._make_pending_request(project, f"cap0_vol_api_{i}") for i in range(5)
        ]

        for r in reqs:
            self.assertEqual(self._approve_api(project, r).status_code, 200)

        for r in reqs:
            r.refresh_from_db()
            self.assertEqual(r.status, "approved")

    # ---- CASE 4: reject frees the slot for another request ----
    def test_case4_reject_then_approve_another_frees_slot_web(self):
        project = self._make_project(max_volunteers=1)
        req_a = self._make_pending_request(project, "cap4_vol_web_a")
        req_b = self._make_pending_request(project, "cap4_vol_web_b")

        self.assertEqual(self._approve_web(req_a).status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.current_volunteers, 1)

        self.assertEqual(self._reject_web(req_a).status_code, 200)
        req_a.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req_a.status, "rejected")
        self.assertEqual(project.current_volunteers, 0)

        resp_b = self._approve_web(req_b)
        self.assertEqual(resp_b.status_code, 200)
        req_b.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req_b.status, "approved")
        self.assertEqual(project.current_volunteers, 1)

    def test_case4_reject_then_approve_another_frees_slot_api(self):
        project = self._make_project(max_volunteers=1)
        req_a = self._make_pending_request(project, "cap4_vol_api_a")
        req_b = self._make_pending_request(project, "cap4_vol_api_b")

        self.assertEqual(self._approve_api(project, req_a).status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.current_volunteers, 1)

        self.assertEqual(self._reject_api(project, req_a).status_code, 200)
        req_a.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req_a.status, "rejected")
        self.assertEqual(project.current_volunteers, 0)

        resp_b = self._approve_api(project, req_b)
        self.assertEqual(resp_b.status_code, 200)
        req_b.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req_b.status, "approved")
        self.assertEqual(project.current_volunteers, 1)

    # ---- CASE 5: duplicate/idempotent approve does not double-reserve ----
    def test_case5_duplicate_approve_is_idempotent_web(self):
        project = self._make_project(max_volunteers=1)
        req = self._make_pending_request(project, "cap5_vol_web")

        self.assertEqual(self._approve_web(req).status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.current_volunteers, 1)

        resp2 = self._approve_web(req)
        self.assertEqual(resp2.status_code, 200)
        req.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertEqual(project.current_volunteers, 1)

    def test_case5_duplicate_approve_is_idempotent_api(self):
        project = self._make_project(max_volunteers=1)
        req = self._make_pending_request(project, "cap5_vol_api")

        self.assertEqual(self._approve_api(project, req).status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.current_volunteers, 1)

        resp2 = self._approve_api(project, req)
        self.assertEqual(resp2.status_code, 200)
        req.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertEqual(project.current_volunteers, 1)
