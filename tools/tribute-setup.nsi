Unicode true
RequestExecutionLevel admin
CRCCheck force
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "x64.nsh"

!define APP_NAME "Foundation Tribute Runner"
!define APP_EXE "FoundationTributeRunner.exe"
!define APP_PATH "$PROGRAMFILES64\${APP_NAME}"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\FoundationTributeRunner"

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
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "TradChinese"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "A 64-bit Windows installation is required."
    Abort
  ${EndIf}
  SetShellVarContext all
  SetRegView 64
  ; Do not accept /D: workers can be elevated, so install only under Program Files.
  StrCpy $INSTDIR "${APP_PATH}"
FunctionEnd

Section
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

Function un.onInit
  SetShellVarContext all
  SetRegView 64
  StrCmp "$INSTDIR" "${APP_PATH}" uninstall_ok
  MessageBox MB_ICONSTOP "Run the uninstaller from the installed app."
  Abort
  uninstall_ok:
FunctionEnd

Section "Uninstall"
  ; Only delete files this setup installed. Per-user logs stay intact.
  ClearErrors
  Delete "$INSTDIR\${APP_EXE}"
  IfErrors uninstall_failed
  !include "${REMOVAL_LIST}"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
  Goto uninstall_done

  uninstall_failed:
    SetErrorLevel 1
    Abort "Close Foundation Tribute Runner before uninstalling."
  uninstall_done:
SectionEnd
