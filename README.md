# Naas Authenticator

Naas Authenticator provides the following features:

* New users can signup on the system;
* New users can be blocked of accessing the system and need an admin authorization;
* Option of increase password security by avoiding common passwords or minimum password length;
* Option to block users after a number attempts of login;
* Option of open signup and no need for initial authorization;
* Option of open change password (open_change_password);
* Option of adding more information about users on signup.


## Documentation

Documentation is available [here](https://naas-authenticator.readthedocs.io)


## Running tests

To run the tests locally, you can install the development dependencies:

`$ pip install -e '.[dev]'`

Then run tests with pytest:

`$ pytest`

