# setup.py
from setuptools import setup, find_packages

setup(
    name="disbelieve",
    version="0.1.25",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "construct",
        "solana",
        "solders",
        "requests",
        "aiohttp",
        "httpx",
        "base58",
        "python-dotenv",
        "readchar"
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "disbelieve = disbelieve.main:run",
            "sell = disbelieve.sell:run",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    author="FLOCK4H",
    description="Believe Platform Sniper Bot",
)