#!/usr/bin/env python3
"""
数据源集成框架安装脚本
"""

from setuptools import setup, find_packages

# 读取 README 文件
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# 读取依赖
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="datasource-integration",
    version="1.0.0",
    author="DataSource Team",
    author_email="your-email@example.com",
    description="统一的金融数据源集成框架",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/datasource-integration",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Office/Business :: Financial",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.7",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-asyncio>=0.21.0",
            "black>=22.0",
            "flake8>=4.0",
            "mypy>=0.950",
        ],
        "docs": [
            "sphinx>=4.0",
            "sphinx-rtd-theme>=1.0",
        ],
    },
    include_package_data=True,
    zip_safe=False,
    keywords="finance, stock, data, tushare, integration",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/datasource-integration/issues",
        "Source": "https://github.com/yourusername/datasource-integration",
        "Documentation": "https://datasource-integration.readthedocs.io/",
    },
)
