from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="jupyterhub-naasauthenticator",
    version="0.3.76",
    description="JupyterHub Native Authenticator",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/cashstory/naasauthenticator",
    author="Martin DONADIEU",
    author_email="bob@cashstory.com",
    license="3 Clause BSD",
    packages=find_packages(),
    extras_require={
        "dev": [
            "codecov",
            "commitizen>=2,<3",
            "flake8>=3,<4",
            "black",
            "pytest>=3.7",
            "pytest-asyncio",
            "pytest-cov>=2,<3",
            "notebook==6.3.0",
        ]
    },
    install_requires=["jupyterhub==1.3.0", "bcrypt"],
    include_package_data=True,
)
