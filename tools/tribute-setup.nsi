Unicode true
RequestExecutionLevel admin
CRCCheck force
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "Sections.nsh"
!include "x64.nsh"

!define APP_NAME "Foundation Tribute Runner"
!define APP_EXE "FoundationTributeRunner.exe"
!define APP_PATH "$PROGRAMFILES64\${APP_NAME}"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\FoundationTributeRunner"
!define DESKTOP_LINK "$DESKTOP\${APP_NAME}.lnk"

Var RegisteredPath
Var DesktopShortcut

Name "${APP_NAME}"
OutFile "${OUTPUT_EXE}"
InstallDir "${APP_PATH}"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "FileDescription" "${APP_NAME} Offline Installer"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "Foundation Tribute Runner contributors"

!define MUI_ABORTWARNING
!define MUI_DIRECTORYPAGE_TEXT_TOP "$(DirectoryHint)"
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirectoryLeave
!insertmacro MUI_PAGE_DIRECTORY
!define MUI_COMPONENTSPAGE_NODESC
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "TradChinese"

LangString DirectoryHint ${LANG_ENGLISH} "Choose a new folder on a local NTFS drive, or keep the current installation folder when upgrading."
LangString DirectoryHint ${LANG_SIMPCHINESE} "请选择本地 NTFS 磁盘上的新文件夹。升级时沿用原安装目录。"
LangString DirectoryHint ${LANG_TRADCHINESE} "請選擇本機 NTFS 磁碟上的新資料夾。升級時沿用原安裝目錄。"
LangString ProgramFilesLabel ${LANG_ENGLISH} "Program files (required)"
LangString ProgramFilesLabel ${LANG_SIMPCHINESE} "程序文件（必需）"
LangString ProgramFilesLabel ${LANG_TRADCHINESE} "程式檔案（必要）"
LangString DesktopOption ${LANG_ENGLISH} "Create a desktop shortcut"
LangString DesktopOption ${LANG_SIMPCHINESE} "创建桌面快捷方式"
LangString DesktopOption ${LANG_TRADCHINESE} "建立桌面捷徑"
LangString InvalidFolder ${LANG_ENGLISH} "Choose a shorter, protected folder on a local NTFS drive, for example Program Files or a new folder on D:. Desktop, Downloads and redirected folders are not supported."
LangString InvalidFolder ${LANG_SIMPCHINESE} "请选择较短的本地 NTFS 安装路径，例如默认路径或 D: 盘下的新文件夹。不能装到桌面、下载、重定向目录或普通用户可修改的位置。"
LangString InvalidFolder ${LANG_TRADCHINESE} "請選擇較短的本機 NTFS 安裝路徑，例如預設路徑或 D: 磁碟下的新資料夾。不能安裝到桌面、下載、重新導向的目錄或一般使用者可修改的位置。"
LangString ExistingInstall ${LANG_ENGLISH} "To change the folder, uninstall the existing version first. Otherwise, keep its current path."
LangString ExistingInstall ${LANG_SIMPCHINESE} "要更换安装路径，请先卸载旧版；直接升级请保留原路径。"
LangString ExistingInstall ${LANG_TRADCHINESE} "若要變更安裝路徑，請先解除安裝舊版；直接升級請保留原路徑。"
LangString FolderNotEmpty ${LANG_ENGLISH} "That folder already contains files. Choose a new or empty folder."
LangString FolderNotEmpty ${LANG_SIMPCHINESE} "这个文件夹已有文件，请选择新文件夹或空文件夹。"
LangString FolderNotEmpty ${LANG_TRADCHINESE} "這個資料夾已有檔案，請選擇新資料夾或空資料夾。"
LangString ShortcutConflict ${LANG_ENGLISH} "An existing desktop shortcut with this name was left unchanged."
LangString ShortcutConflict ${LANG_SIMPCHINESE} "桌面已有同名快捷方式，已保留原快捷方式。"
LangString ShortcutConflict ${LANG_TRADCHINESE} "桌面已有同名捷徑，已保留原捷徑。"
LangString ShortcutFailed ${LANG_ENGLISH} "The desktop shortcut could not be updated. The Start menu shortcut is still available."
LangString ShortcutFailed ${LANG_SIMPCHINESE} "无法更新桌面快捷方式，仍可从开始菜单打开。"
LangString ShortcutFailed ${LANG_TRADCHINESE} "無法更新桌面捷徑，仍可從開始功能表開啟。"

; This function is also called for silent installs, where page callbacks aren't run.
Function CheckInstallFolder
  Pop $0
  ; The target may not exist yet. Validate the selected path without resolving it.
  StrCpy $1 $INSTDIR 1 -1
  ${If} $1 == "\"
    StrCpy $INSTDIR $INSTDIR -1
  ${EndIf}
  InitPluginsDir
  File /oname=$PLUGINSDIR\SetupLocation.exe "${LOCATION_HELPER}"
  StrCpy $2 $INSTDIR
  StrCpy $3 $RegisteredPath
  System::Call 'kernel32::SetEnvironmentVariableW(w "FTR_SETUP_PATH", w r2) i .r1'
  ${If} $1 == 0
    Push 15
    Return
  ${EndIf}
  System::Call 'kernel32::SetEnvironmentVariableW(w "FTR_SETUP_REGISTERED_PATH", w r3) i .r1'
  ${If} $1 == 0
    Push 15
    Return
  ${EndIf}
  nsExec::Exec /TIMEOUT=15000 '"$PLUGINSDIR\SetupLocation.exe" $0 ${MAX_INSTALL_PATH}'
FunctionEnd

Function ShowFolderError
  Pop $0
  ${If} $0 == 12
    MessageBox MB_ICONEXCLAMATION "$(ExistingInstall)" /SD IDOK
  ${ElseIf} $0 == 14
    MessageBox MB_ICONEXCLAMATION "$(FolderNotEmpty)" /SD IDOK
  ${Else}
    MessageBox MB_ICONEXCLAMATION "$(InvalidFolder)" /SD IDOK
  ${EndIf}
FunctionEnd

Function DirectoryLeave
  Push "check"
  Call CheckInstallFolder
  Pop $0
  ${If} $0 != 0
    Push $0
    Call ShowFolderError
    Abort
  ${EndIf}
FunctionEnd

Section "$(ProgramFilesLabel)" SecProgram
  SectionIn RO
  Push "prepare"
  Call CheckInstallFolder
  Pop $0
  ${If} $0 != 0
    Push $0
    Call ShowFolderError
    SetErrorLevel 1
    Abort
  ${EndIf}

  SetOutPath "$INSTDIR"
  ClearErrors
  File /r "${PAYLOAD_DIR}\*"
  IfErrors install_failed

  CreateShortCut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  IfErrors install_failed

  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "Foundation Tribute Runner contributors"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "URLInfoAbout" "https://github.com/David-Lzy/foundation.game_audoguild"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "EstimatedSize" ${PAYLOAD_KIB}
  IfErrors install_failed
  Goto install_done

  install_failed:
    SetErrorLevel 1
    Abort "Installation failed. Close the launcher and try again."
  install_done:
SectionEnd

Section /o "$(DesktopOption)" SecDesktop
  ${If} $DesktopShortcut != 1
    ${AndIf} ${FileExists} "${DESKTOP_LINK}"
    DetailPrint "$(ShortcutConflict)"
  ${Else}
    ClearErrors
    CreateShortCut "${DESKTOP_LINK}" "$INSTDIR\${APP_EXE}"
    ${If} ${Errors}
      DetailPrint "$(ShortcutFailed)"
    ${Else}
      StrCpy $DesktopShortcut 1
    ${EndIf}
  ${EndIf}
SectionEnd

Section -Finish
  ${IfNot} ${SectionIsSelected} ${SecDesktop}
    ${AndIf} $DesktopShortcut == 1
    ClearErrors
    ${If} ${FileExists} "${DESKTOP_LINK}"
      Delete "${DESKTOP_LINK}"
    ${EndIf}
    ${If} ${Errors}
      DetailPrint "$(ShortcutFailed)"
    ${Else}
      StrCpy $DesktopShortcut 0
    ${EndIf}
  ${EndIf}
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "DesktopShortcut" $DesktopShortcut
SectionEnd

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "A 64-bit Windows installation is required."
    Abort
  ${EndIf}
  SetShellVarContext all
  SetRegView 64
  ReadRegStr $RegisteredPath HKLM "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $RegisteredPath != ""
    StrCpy $INSTDIR $RegisteredPath
  ${EndIf}
  ReadRegDWORD $DesktopShortcut HKLM "${UNINSTALL_KEY}" "DesktopShortcut"
  ${If} $DesktopShortcut == 1
    !insertmacro SelectSection ${SecDesktop}
  ${Else}
    StrCpy $DesktopShortcut 0
  ${EndIf}
FunctionEnd

Function un.onInit
  SetShellVarContext all
  SetRegView 64
  ReadRegStr $RegisteredPath HKLM "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $RegisteredPath == ""
    ${OrIf} $INSTDIR != $RegisteredPath
    MessageBox MB_ICONSTOP "Run the uninstaller from the registered installation folder." /SD IDOK
    Abort
  ${EndIf}
  ReadRegDWORD $DesktopShortcut HKLM "${UNINSTALL_KEY}" "DesktopShortcut"
FunctionEnd

Section "Uninstall"
  ; Only delete files this setup installed. Per-user logs stay intact.
  ClearErrors
  Delete "$INSTDIR\${APP_EXE}"
  IfErrors uninstall_failed
  !include "${REMOVAL_LIST}"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  ${If} $DesktopShortcut == 1
    Delete "${DESKTOP_LINK}"
  ${EndIf}
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
  Goto uninstall_done

  uninstall_failed:
    SetErrorLevel 1
    Abort "Close Foundation Tribute Runner before uninstalling."
  uninstall_done:
SectionEnd
