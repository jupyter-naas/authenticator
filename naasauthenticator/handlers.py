from jinja2 import ChoiceLoader, FileSystemLoader
from jupyterhub.handlers.login import LoginHandler
from jupyterhub.handlers import BaseHandler
from tornado.httputil import url_concat
from jupyterhub.utils import admin_only
from tornado.escape import url_escape
from .orm import UserInfo
from tornado import web
import requests
import secrets
import os


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


class LocalBase(BaseHandler):
    def __init__(self, *args, **kwargs):
        self._loaded = False
        super().__init__(*args, **kwargs)

    def _register_template_path(self):
        if self._loaded:
            return
        self.log.debug("Adding %s to template path", TEMPLATE_DIR)
        loader = FileSystemLoader([TEMPLATE_DIR])
        env = self.settings["jinja2_env"]
        previous_loader = env.loader
        env.loader = ChoiceLoader([previous_loader, loader])
        self._loaded = True


class SignUpHandler(LocalBase):
    """Render the sign in page."""

    @admin_only
    async def get(self):
        res = self.authenticator.get_users()
        users = [item.to_dict() for item in res]
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
            self.get_body_argument("username", strip=False)
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
            "is_authorized": True,
            "email": self.get_body_argument("username", "", strip=False),
            "admin": self.get_body_argument("admin", False, strip=False),
        }
        alert, message = "", ""
        userExist = self.authenticator.get_user(**user_info)
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
        res = UserInfo.get_all(self.db)
        if mimetype == "application/json":
            users = [item.to_dict() for item in res]
            self.finish({"data": users})
        else:
            self._register_template_path()
            html = self.render_template(
                "autorization-area.html",
                ask_email=self.authenticator.ask_email_on_signup,
                users=res,
            )
            self.finish(html)


class ChangeAuthorizationHandler(LocalBase):
    @admin_only
    async def put(self, slug):
        is_authorized = self.get_body_argument("username", strip=False)
        user = UserInfo.update_authorization(self.db, slug, is_authorized)
        self.finish({"data": user})

    @admin_only
    async def get(self, slug):
        mimetype = self.request.headers.get("content-type", None)
        if mimetype == "application/json":
            data = UserInfo.get_authorization(self.db, slug)
            self.finish({"data": {"username": slug, "is_authorized": data}})
        else:
            UserInfo.change_authorization(self.db, slug)
            self.redirect(self.hub.base_url + "authorize")


class ResetPasswordHandler(LocalBase):
    async def get(self):
        html = self.render_template(
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
        html = self.render_template(
            "reset-password.html",
            result_message=message,
            alert=alert,
        )
        self.finish(html)


class DeleteHandler(LocalBase):
    @admin_only
    async def get(self, slug):
        mimetype = self.request.headers.get("content-type", None)
        data = UserInfo.delete_user(self.db, slug)
        if mimetype == "application/json":
            self.finish({"data": data})
        else:
            self.redirect("/authorize")


class ChangePasswordHandler(LocalBase):
    """Render the reset password page."""

    @web.authenticated
    async def get(self):
        user = await self.get_current_user()
        html = self.render_template(
            "change-password.html",
            user_name=user.name,
        )
        self.finish(html)

    @web.authenticated
    async def post(self):
        user = await self.get_current_user()
        new_password = self.get_body_argument("password", strip=False)
        self.authenticator.change_password(user.name, new_password)

        html = self.render_template(
            "change-password.html",
            user_name=user.name,
            result_message="Your password has been changed successfully",
        )
        self.finish(html)

    @admin_only
    async def put(self):
        username = self.get_body_argument("username", strip=False)
        user = self.authenticator.get_user(username, None)
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


class LoginHandler(LoginHandler, LocalBase):
    def _render(self, login_error=None, username=None):
        self._register_template_path()
        landing_url = os.getenv("LANDING_URL")
        crisp_website_id = os.getenv("CRISP_WEBSITE_ID")
        return self.render_template(
            "native-login.html",
            next=url_escape(self.get_argument("next", default="")),
            username=username,
            login_error=login_error,
            custom_html=self.authenticator.custom_html,
            login_url=self.settings["login_url"],
            landing_url=landing_url,
            crisp_website_id=crisp_website_id,
            authenticator_login_url=url_concat(
                self.authenticator.login_url(self.hub.base_url),
                {"next": self.get_argument("next", "")},
            ),
        )
