# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
from setuptools import find_packages, setup

setup(
    name="slicerswap",
    version="0.2.2.dev0",  # 0.2.2-wip
    description="Convert, back up and install profiles, printers and plug-ins for Cura, PrusaSlicer and OrcaSlicer (work in progress)",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Matthew Armstrong",
    author_email="The-Dorkknight@users.noreply.github.com",
    url="https://github.com/The-Dorkknight/slicer-swap",
    license="PolyForm-Noncommercial-1.0.0",
    packages=find_packages(exclude=("tests", "tools")),
    include_package_data=True,
    package_data={"slicerswap": ["data/*.json", "data/*.png", "data/cura/*", "data/cura/**/*"]},
    python_requires=">=3.8",
    entry_points={"console_scripts": ["slicerswap=slicerswap.cli:main"]},
    classifiers=["Development Status :: 2 - Pre-Alpha", "License :: Other/Proprietary License",
                 "Programming Language :: Python :: 3", "Environment :: X11 Applications :: Tk",
                 "Topic :: Multimedia :: Graphics :: 3D Modeling"],
)
