# La màquina de fer xurros

### OS Independent
#### Install pre-commit:
```bash
pip install pre-commit
pre-commit install
```
With this, pre-commit will run before every commit, checking for code style and formatting.

For specific information check the `.pre-commit-config.yaml` file.

### Windows
#### Install ffmpeg:

Run terminal as administrator

```
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

```
choco install ffmpeg-full
```

#### Install ImageMagick:

https://imagemagick.org/archive/binaries #/ImageMagick-6.9.13-16-Q16-HDRI-x64-dll.exe



pip install imageio[ffmpeg]


pip install git+https://github.com/jpgallegoar/Spanish-F5.git


pip install -r .\requirements.txt --ignore-requires-python
