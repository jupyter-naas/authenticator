from jinja2 import ChoiceLoader, FileSystemLoader
from jupyterhub.handlers.login import LoginHandler
from jupyterhub.handlers import BaseHandler
from tornado.httputil import url_concat
from jupyterhub.utils import admin_only
from urllib.parse import urlparse
from tornado.escape import url_escape
from types import SimpleNamespace
from .orm import UserInfo
from tornado import web
import requests
import secrets
import os


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def url_path_join(*pieces):
    """Join components of url into a relative url.
    Use to prevent double slash when joining subpath. This will leave the
    initial and final / in place.
    Copied from `notebook.utils.url_path_join`.
    """
    initial = pieces[0].startswith("/")
    final = pieces[-1].endswith("/")
    stripped = [s.strip("/") for s in pieces]
    result = "/".join(s for s in stripped if s)

    if initial:
        result = "/" + result
    if final:
        result = result + "/"
    if result == "//":
        result = "/"

    return result


class LocalBase(BaseHandler):
    _template_dir_registered = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not LocalBase._template_dir_registered:
            self.log.debug("Adding %s to template path", TEMPLATE_DIR)
            loader = FileSystemLoader([TEMPLATE_DIR])
            env = self.settings["jinja2_env"]
            previous_loader = env.loader
            env.loader = ChoiceLoader([previous_loader, loader])
            LocalBase._template_dir_registered = True

    def get_next_url(self, user=None, default=None):
        """Get the next_url for login redirect
        Default URL after login:
        - if redirect_to_server (default): send to user's own server
        - else: /hub/home
        """
        next_url = self.get_argument("next", default="")
        # protect against some browsers' buggy handling of backslash as slash
        next_url = next_url.replace("\\", "%5C")
        if (next_url + "/").startswith(
            (
                "%s://%s/" % (self.request.protocol, self.request.host),
                "//%s/" % self.request.host,
            )
        ) or (
            self.subdomain_host
            and urlparse(next_url).netloc
            and ("." + urlparse(next_url).netloc).endswith(
                "." + urlparse(self.subdomain_host).netloc
            )
        ):
            # treat absolute URLs for our host as absolute paths:
            # below, redirects that aren't strictly paths
            parsed = urlparse(next_url)
            next_url = parsed.path
            if parsed.query:
                next_url = next_url + "?" + parsed.query
            if parsed.fragment:
                next_url = next_url + "#" + parsed.fragment

        # if it still has host info, it didn't match our above check for *this* host
        if next_url and (
            ("://" in next_url and next_url.index("://") < next_url.index("?"))
            or next_url.startswith("//")
            or not next_url.startswith("/")
        ):
            self.log.warning("Disallowing redirect outside JupyterHub: %r", next_url)
            next_url = ""

        if next_url and next_url.startswith(url_path_join(self.base_url, "user/")):
            # add /hub/ prefix, to ensure we redirect to the right user's server.
            # The next request will be handled by SpawnHandler,
            # ultimately redirecting to the logged-in user's server.
            without_prefix = next_url[len(self.base_url) :]  # noqa: E203
            next_url = url_path_join(self.hub.base_url, without_prefix)
            self.log.warning(
                "Redirecting %s to %s. For sharing public links, use /user-redirect/",
                self.request.uri,
                next_url,
            )

        # this is where we know if next_url is coming from ?next= param or we are using a default url
        if next_url:
            next_url_from_param = True
        else:
            next_url_from_param = False

        if not next_url:
            # custom default URL, usually passed because user landed on that page but was not logged in
            if default:
                next_url = default
            else:
                # As set in jupyterhub_config.py
                if callable(self.default_url):
                    next_url = self.default_url(self)
                else:
                    next_url = self.default_url

        if not next_url:
            # default URL after login
            # if self.redirect_to_server, default login URL initiates spawn,
            # otherwise send to Hub home page (control panel)
            if user and self.redirect_to_server:
                if user.spawner.active:
                    # server is active, send to the user url
                    next_url = user.url
                else:
                    # send to spawn url
                    next_url = url_path_join(self.hub.base_url, "spawn")
            else:
                next_url = url_path_join(self.hub.base_url, "home")

        if not next_url_from_param:
            # when a request made with ?next=... assume all the params have already been encoded
            # otherwise, preserve params from the current request across the redirect
            next_url = self.append_query_parameters(next_url, exclude=["next"])
        return next_url


class SignUpHandler(LocalBase):
    """Render the sign in page."""

    @admin_only
    async def get(self):
        res = self.authenticator.get_users()
        users = [item.as_dict() for item in res]
        response = {
            "data": users,
            "message": "Here the list of users",
        }
        self.finish(response)
        return response

    def get_result_message(self, user):
        alert = "alert-success"
        message = (
            "The signup was successful. You can now go to "
            "home page and log in the system"
        )
        if not user:
            alert = "alert-danger"
            password_len = self.authenticator.minimum_password_length

            if password_len:
                message = (
                    "Something went wrong. Be sure your password has "
                    "at least {} characters, doesn't have spaces or "
                    "commas and is not too common."
                ).format(password_len)

            else:
                message = (
                    "Something went wrong. Be sure your password "
                    " doesn't have spaces or commas and is not too "
                    "common."
                )

        return alert, message

    @admin_only
    async def delete(self):
        user = self.authenticator.delete_user(
            SimpleNamespace(name=self.get_body_argument("username", strip=False))
        )
        response = {
            "data": user,
            "message": "User deleted",
        }
        self.finish(response)
        return response

    @admin_only
    async def post(self):
        user_info = {
            "username": self.get_body_argument("username", strip=False),
            "password": self.get_body_argument("password", strip=False),
            "is_authorized": self.get_body_argument("is_authorized", True, strip=False),
            "email": self.get_body_argument("username", "", strip=False),
            "admin": self.get_body_argument("admin", False, strip=False),
        }
        alert, message = "", ""
        userExist = self.authenticator.user_exists(user_info["username"])
        if userExist:
            alert = "alert-danger"
            message = "User already exist"
        else:
            user = self.authenticator.create_user(**user_info)
            alert, message = self.get_result_message(user)

        response = {
            "name": user_info.get("username"),
            "message": message,
        }
        if alert == "alert-danger":
            response["error"] = True

        self.finish(response)
        return response


class AuthorizationHandler(LocalBase):
    """Render the sign in page."""

    @admin_only
    async def get(self):
        mimetype = self.request.headers.get("content-type", None)
        res = self.authenticator.get_users()
        if mimetype == "application/json":
            users = [item.as_dict() for item in res]
            self.finish({"data": users})
        else:
            html = await self.render_template(
                "autorization-area.html",
                ask_email=self.authenticator.ask_email_on_signup,
                users=res,
            )
            self.finish(html)


class ChangeAuthorizationHandler(LocalBase):
    @admin_only
    async def post(self, slug):
        is_authorized = self.get_body_argument("is_authorized", True, strip=False)
        is_authorized = True if is_authorized and is_authorized == "true" else False
        UserInfo.update_authorization(self.db, slug, is_authorized)
        self.finish({"data": {"username": slug, "is_authorized": is_authorized}})

    @admin_only
    async def get(self, slug):
        mimetype = self.request.headers.get("content-type", None)
        if mimetype == "application/json":
            data = UserInfo.get_authorization(self.db, slug)
            res = {"data": {"username": slug, "is_authorized": data}}
            self.finish(res)
        else:
            UserInfo.change_authorization(self.db, slug)
            self.redirect(self.hub.base_url + "authorize")


class ResetPasswordHandler(LocalBase):
    async def get(self):
        html = await self.render_template(
            "reset-password.html",
        )
        self.finish(html)

    async def post(self):
        username = self.get_body_argument("username", strip=False)
        message = "Check your emails"
        alert = "alert-success"
        new_password = secrets.token_hex(16)
        message = "Your link to reset password has been send successfully"
        self.authenticator.change_password(username, new_password)
        signup_url = f"{os.environ.get('NOTIFICATIONS_API', None)}/send"
        html = """
        You asked to reset your password,
        <br/>Copy this temporary password :
        <br/>{TEMP_PASSWORD}
        <br/>Then connect to this page and change it :
        <a href="{RESET_URL}">Change my password</a>
        <br/><br/>If you never asked to reset, contact us in the chat box on our <a href="{WEBSITE_URL}">website</a>.
        """
        html = html.replace("{TEMP_PASSWORD}", new_password)
        html = html.replace(
            "{RESET_URL}",
            f'{os.environ.get("JUPYTERHUB_URL", "")}/hub/login?next=%2Fhub%2Fchange-password',
        )
        html = html.replace("{WEBSITE_URL}", os.environ.get("JUPYTERHUB_URL", ""))
        content = html
        data = {
            "subject": "Naas Reset password",
            "email": username,
            "content": content,
            "html": html,
        }
        headers = {"Authorization": os.environ.get("NOTIFICATIONS_ADMIN_TOKEN", None)}
        try:
            r = requests.post(signup_url, json=data, headers=headers)
            r.raise_for_status()
        except requests.HTTPError as err:
            alert = "alert-danger"
            message = f"Something wrong happen {err}"
        response = {
            "name": username,
            "message": message,
        }
        if alert == "alert-danger":
            response["error"] = True
        html = await self.render_template(
            "reset-password.html",
            result_message=message,
            alert=alert,
        )
        self.finish(html)


class DeleteHandler(LocalBase):
    @web.authenticated
    async def get(self, slug):
        user = await self.get_current_user()
        username = None
        if user.admin is True:
            username = slug
        else:
            username = user.name
        mimetype = self.request.headers.get("content-type", None)
        data = UserInfo.delete_user(self.db, username)
        if mimetype == "application/json":
            self.finish({"data": data})
        else:
            self.redirect("/logout")


class ChangePasswordHandler(LocalBase):
    """Render the reset password page."""

    @web.authenticated
    async def get(self):
        user = await self.get_current_user()
        html = await self.render_template(
            "change-password.html",
            user_name=user.name,
        )
        self.finish(html)

    @web.authenticated
    async def post(self):
        user = await self.get_current_user()
        new_password = self.get_body_argument("password", strip=False)
        self.authenticator.change_password(user.name, new_password)

        html = await self.render_template(
            "change-password.html",
            user_name=user.name,
            result_message="Your password has been changed successfully",
        )
        self.finish(html)

    @admin_only
    async def put(self):
        username = self.get_body_argument("username", strip=False)
        user = self.authenticator.get_user(username)
        message = ""
        alert = "alert-success"
        new_password = self.get_body_argument("password", strip=False)
        message = "Your password has been changed successfully"
        self.authenticator.change_password(user.name, new_password)

        response = {
            "name": username,
            "message": message,
        }
        if alert == "alert-danger":
            response["error"] = True

        self.finish(response)
        return response


class ChangePasswordAdminHandler(LocalBase):
    """Render the reset password page."""

    @admin_only
    async def get(self, user_name):
        if not self.authenticator.user_exists(user_name):
            raise web.HTTPError(404)
        html = await self.render_template(
            "change-password.html",
            user_name=user_name,
        )
        self.finish(html)

    @admin_only
    async def post(self, user_name):
        new_password = self.get_body_argument("password", strip=False)
        self.authenticator.change_password(user_name, new_password)

        message_template = "The password for {} has been changed successfully"
        html = await self.render_template(
            "change-password.html",
            user_name=user_name,
            result_message=message_template.format(user_name),
        )
        self.finish(html)


class LoginHandler(LoginHandler, LocalBase):
    async def post(self):
        # parse the arguments dict
        data = {}
        for arg in self.request.arguments:
            data[arg] = self.get_argument(arg, strip=False)

        auth_timer = self.statsd.timer("login.authenticate").start()
        user = await self.login_user(data)
        auth_timer.stop(send=False)

        if user:
            # register current user for subsequent requests to user (e.g. logging the request)
            self._jupyterhub_user = user
            self.redirect(self.get_next_url(user))
        else:
            error_message = "Invalid username or password"
            if "error" in data:
                error_message = data["error"]
            html = await self._render(
                login_error=error_message, username=data["username"]
            )
            self.finish(html)

    async def get(self):
        self.statsd.incr("login.request")
        user = self.current_user
        if user:
            # set new login cookie
            # because single-user cookie may have been cleared or incorrect
            self.set_login_cookie(user)
            self.redirect(self.get_next_url(user), permanent=False)
        if self.get_argument("bearer", default=False):
            bearer = self.get_argument("bearer")

            auth_timer = self.statsd.timer("login.authenticate").start()
            data = {"bearer": bearer}
            user = await self.login_user(data)

            auth_timer.stop(send=False)

            if user:
                # register current user for subsequent requests to user (e.g. logging the request)

                # TODO: Need to set cookie for subsequent queries (allow naas manager to authenticate user as well)

                self._jupyterhub_user = user
                self.redirect(self.get_next_url(user))
            else:
                error_message = "Invalid bearer token!"
                if "error" in data:
                    error_message = data["error"]

                html = await self._render(login_error=error_message)
                self.finish(html)
                return
        else:
            if self.authenticator.auto_login:
                auto_login_url = self.authenticator.login_url(self.hub.base_url)
                if auto_login_url == self.settings["login_url"]:
                    # auto_login without a custom login handler
                    # means that auth info is already in the request
                    # (e.g. REMOTE_USER header)
                    user = await self.login_user()
                    if user is None:
                        # auto_login failed, just 403
                        raise web.HTTPError(403)
                    else:
                        self.redirect(self.get_next_url(user))
                else:
                    if self.get_argument("next", default=False):
                        auto_login_url = url_concat(
                            auto_login_url, {"next": self.get_next_url()}
                        )
                    self.redirect(auto_login_url)
                return
            username = self.get_argument("username", default="")
            self.finish(await self._render(username=username))

    def _render(self, login_error=None, username=None):
        landing_url = os.getenv("LANDING_URL")
        crisp_website_id = os.getenv("CRISP_WEBSITE_ID")
        auth_url = os.getenv("AUTH_URL", "http://127.0.0.1:5000")

        return self.render_template(
            "native-login.html",
            next=url_escape(self.get_argument("next", default="/hub")),
            username=username,
            login_error=login_error,
            custom_html=self.authenticator.custom_html,
            login_url=self.settings["login_url"],
            landing_url=landing_url,
            crisp_website_id=crisp_website_id,
            auth_url=auth_url,
            authenticator_login_url=url_concat(
                self.authenticator.login_url(self.hub.base_url),
                {"next": self.get_argument("next", "")},
            ),
        )
