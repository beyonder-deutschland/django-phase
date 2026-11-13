from ambient_package_update.metadata.author import PackageAuthor
from ambient_package_update.metadata.constants import (
    DEPLOYMENT_STATUS_BETA,
    DEV_DEPENDENCIES,
    LICENSE_MIT,
    SUPPORTED_DJANGO_VERSIONS,
    SUPPORTED_PYTHON_VERSIONS,
)
from ambient_package_update.metadata.maintainer import PackageMaintainer
from ambient_package_update.metadata.package import PackageMetadata
from ambient_package_update.metadata.readme import ReadmeContent

METADATA = PackageMetadata(
    package_name="django_phase",
    module_name="phase",
    github_package_group="beyonder-deutschland",
    authors=[
        PackageAuthor(
            name="Beyonder Deutschland",
            email="hello@beyonder.de",
        ),
    ],
    maintainer=PackageMaintainer(name="Beyonder Deutschland", url="https://beyonder.de/", email="hello@beyonder.de"),
    licenser="Beyonder Deutschland GmbH",
    license=LICENSE_MIT,
    license_year=2026,
    development_status=DEPLOYMENT_STATUS_BETA,
    has_migrations=False,
    main_branch="main",
    claim="Race-safe state machines for Django",
    readme_content=ReadmeContent(uses_internationalisation=False),
    dependencies=[
        f"Django>={SUPPORTED_DJANGO_VERSIONS[0]}",
    ],
    supported_django_versions=SUPPORTED_DJANGO_VERSIONS,
    supported_python_versions=SUPPORTED_PYTHON_VERSIONS,
    optional_dependencies={
        "dev": [
            *DEV_DEPENDENCIES,
        ],
    },
    ruff_ignore_list=[],
)
