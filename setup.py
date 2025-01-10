from setuptools import setup, find_packages

# Read the contents of your README file
# with open("README.md", "r") as fh:
#     long_description = fh.read()


setup(
    name='compress',  # Replace with your package name
    version='0.1.0',      # Replace with your package version
    author='namindu De Silva',
    author_email='nami.rangana@gmail.com',
    description='Compress MD trajectories using deep convolutional autoencoder',
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",  # Specify the README format
    url='https://github.com/nami-rangana/Compress.git',  # Optional
    packages=find_packages(),   # Automatically find packages within your project
    classifiers=[               # Optional classifiers for PyPI
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License", # Choose your license
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',    # Specify minimum Python version
    install_requires=[  
        'torch >= 2.5.1',
        'torchvision >= 2.5.1',
        'torchaudio >= 2.5.1',
        'pytorch-lightning >= 2.4.0'
        'mdtraj >= 1.10.2',
        'scikit-learn >= 1.6.0',
        'numpy >= 2.2.0',
        'tqdm'
    ],
    # entry_points={
    #     '[REDACTED]': [
    #         'compress = [REDACTED].compress',
    #         'decompress = [REDACTED].decompress',
    #     ],
    # }
)