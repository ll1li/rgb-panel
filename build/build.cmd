@echo off
:: Local reproduction of scripts\build-windows.bat for this PC:
:: Qt 5.15.2 msvc2019_64 from aqtinstall (CI uses 5.15.0, same ABI), VS 2022 Build Tools, jom.
SET "BUILD=%~dp0"
SET "QTDIR=%BUILD%Qt\5.15.2\msvc2019_64"
SET "PATH=%PATH%;%QTDIR%\bin;%BUILD%jom"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 exit /b 1
cd /d "%BUILD%OpenRGB"
qmake OpenRGB.pro CONFIG-=debug_and_release CONFIG+=release
if errorlevel 1 exit /b 2
jom
if errorlevel 1 exit /b 3
windeployqt --no-patchqt --no-quick-import --no-translations --no-system-d3d-compiler --no-compiler-runtime --no-opengl-sw --no-network .\release\
if errorlevel 1 exit /b 4
echo BUILD_OK
