import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="app_test_suite",
    version="0.1.2",
    author="Łukasz Piątkowski",
    author_email="lukasz@giantswarm.io",
    description="An app testing suite for GiantSwarm app platform",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/giantswarm/app-test-suite",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)
