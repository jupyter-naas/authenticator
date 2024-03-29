import dbm
import os
import pytest

# import time
from jupyterhub.tests.mocking import MockHub

from naasauthenticator import NaasAuthenticator
from ..orm import UserInfo


@pytest.fixture
def tmpcwd(tmpdir):
    tmpdir.chdir()


@pytest.fixture
def app():
    hub = MockHub()
    hub.init_db()
    return hub


# use pytest-asyncio
pytestmark = pytest.mark.asyncio
# run each test in a temporary working directory
pytestmark = pytestmark(pytest.mark.usefixtures("tmpcwd"))


@pytest.mark.parametrize(
    "is_admin,expected_authorization",
    [
        (False, False),
        (True, True),
        (False, True),
    ],
)
async def test_create_user(is_admin, expected_authorization, tmpcwd, app):
    """Test method create_user for new user and authorization"""
    auth = NaasAuthenticator(db=app.db)

    if is_admin:
        auth.admin_users = {"johnsnow"}

    auth.create_user("johnsnow", "password")
    if expected_authorization:
        UserInfo.change_authorization(app.db, "johnsnow")
    user_info = UserInfo.find(app.db, "johnsnow")
    assert user_info.username == "johnsnow"
    assert user_info.is_authorized == expected_authorization
    assert user_info.is_authorized == UserInfo.get_authorization(app.db, "johnsnow")

    UserInfo.change_authorization(app.db, "johnsnow")
    assert UserInfo.get_authorization(app.db, "johnsnow") != expected_authorization
    UserInfo.update_authorization(app.db, "johnsnow", expected_authorization)
    assert UserInfo.get_authorization(app.db, "johnsnow") == expected_authorization


async def test_create_user_bas_characters(tmpcwd, app):
    """Test method create_user with bad characters on username"""
    auth = NaasAuthenticator(db=app.db)
    assert not auth.create_user("john snow", "password")
    assert not auth.create_user("john,snow", "password")


@pytest.mark.parametrize(
    "password,min_len,expected",
    [
        ("qwerty", 1, False),
        ("agameofthrones", 1, True),
        ("agameofthrones", 15, False),
        ("averyveryverylongpassword", 15, True),
    ],
)
async def test_create_user_with_strong_passwords(
    password, min_len, expected, tmpcwd, app
):
    """Test if method create_user and strong passwords"""
    auth = NaasAuthenticator(db=app.db)
    auth.check_common_password = True
    auth.minimum_password_length = min_len
    user = auth.create_user("johnsnow", password)
    assert bool(user) == expected


@pytest.mark.parametrize(
    "username,password,authorized,expected",
    [
        ("name", "123", False, False),
        ("johnsnow", "123", True, False),
        ("Snow", "password", True, False),
        ("johnsnow", "password", False, False),
        ("johnsnow", "password", True, True),
    ],
)
async def test_authentication(username, password, authorized, expected, tmpcwd, app):
    """Test if authentication fails with a unexistent user"""
    auth = NaasAuthenticator(db=app.db)
    auth.create_user("johnsnow", "password")
    if authorized:
        UserInfo.change_authorization(app.db, "johnsnow")
    response = await auth.authenticate(
        app, {"username": username, "password": password}
    )
    assert bool(response) == expected


async def test_handlers(app):
    """Test if all handlers are available on the Authenticator"""
    auth = NaasAuthenticator(db=app.db)
    handlers = auth.get_handlers(app)
    assert handlers[0][0] == "/login"
    assert handlers[1][0] == "/signup"
    assert handlers[2][0] == "/authorize"
    assert handlers[3][0] == "/authorize/([^/]*)"
    assert handlers[4][0] == "/delete/([^/]*)"
    assert handlers[5][0] == "/reset-password"
    assert handlers[6][0] == "/change-password"
    assert handlers[7][0] == "/change-password/([^/]+)"


async def test_add_new_attempt_of_login(tmpcwd, app):
    auth = NaasAuthenticator(db=app.db)

    assert not auth.login_attempts
    auth.add_login_attempt("username")
    assert auth.login_attempts["username"]["count"] == 1
    auth.add_login_attempt("username")
    assert auth.login_attempts["username"]["count"] == 2


async def test_authentication_login_count(tmpcwd, app):
    auth = NaasAuthenticator(db=app.db)
    infos = {"username": "johnsnow", "password": "password"}
    wrong_infos = {"username": "johnsnow", "password": "wrong_password"}
    auth.create_user(infos["username"], infos["password"])
    UserInfo.change_authorization(app.db, "johnsnow")

    assert not auth.login_attempts

    await auth.authenticate(app, wrong_infos)
    assert auth.login_attempts["johnsnow"]["count"] == 1

    await auth.authenticate(app, wrong_infos)
    assert auth.login_attempts["johnsnow"]["count"] == 2

    await auth.authenticate(app, infos)
    assert not auth.login_attempts.get("johnsnow")


async def test_authentication_with_exceed_atempts_of_login(tmpcwd, app):
    auth = NaasAuthenticator(db=app.db)
    auth.allowed_failed_logins = 3
    auth.secs_before_next_try = 10

    infos = {"username": "johnsnow", "password": "wrongpassword"}
    auth.create_user(infos["username"], "password")
    UserInfo.change_authorization(app.db, "johnsnow")

    for i in range(3):
        response = await auth.authenticate(app, infos)
        assert not response

    infos["password"] = "password"
    response = await auth.authenticate(app, infos)
    assert not response
    # TODO fix this test
    # time.sleep(12)
    # response = await auth.authenticate(app, infos)
    # assert response


async def test_change_password(tmpcwd, app):
    auth = NaasAuthenticator(db=app.db)
    user = auth.create_user("johnsnow", "password")
    assert user.is_valid_password("password")
    auth.change_password("johnsnow", "newpassword")
    assert not user.is_valid_password("password")
    assert user.is_valid_password("newpassword")


async def test_list_users(tmpcwd, app):
    auth = NaasAuthenticator(db=app.db)
    auth.create_user("johnsnow", "password")
    auth.create_user("johnsnow2", "password2")

    res = auth.get_users()
    users = [item.as_dict() for item in res]
    assert len(users) == 3
    user = dict(users[0])
    assert type(user) == dict


async def test_delete_user(tmpcwd, app):
    auth = NaasAuthenticator(db=app.db)
    auth.create_user("johnsnow", "password")

    user = type("User", (), {"name": "johnsnow"})
    auth.delete_user(user)

    user_info = UserInfo.find(app.db, "johnsnow")
    assert not user_info


async def test_import_from_firstuse_dont_delete_db_after(tmpcwd, app):
    with dbm.open("passwords.dbm", "c", 0o600) as db:
        db["user1"] = "password"

    auth = NaasAuthenticator(db=app.db)
    auth.add_data_from_firstuse()

    files = os.listdir()
    assert UserInfo.find(app.db, "user1")
    assert ("passwords.dbm" in files) or ("passwords.dbm.db" in files)


async def test_import_from_firstuse_delete_db_after(tmpcwd, app):
    with dbm.open("passwords.dbm", "c", 0o600) as db:
        db["user1"] = "password"

    auth = NaasAuthenticator(db=app.db)
    auth.delete_firstuse_db_after_import = True

    auth.add_data_from_firstuse()
    files = os.listdir()
    assert UserInfo.find(app.db, "user1")
    assert ("passwords.dbm" not in files) and ("passwords.dbm.db" not in files)


@pytest.mark.parametrize(
    "user,pwd",
    [
        ("user1", "password"),
        ("user 1", "somethingelsereallysecure"),
    ],
)
async def test_import_from_firstuse_invalid_password(user, pwd, tmpcwd, app):
    with dbm.open("passwords.dbm", "c", 0o600) as db:
        db[user] = pwd

    auth = NaasAuthenticator(db=app.db)
    auth.check_common_password = True
    with pytest.raises(ValueError):
        auth.add_data_from_firstuse()
