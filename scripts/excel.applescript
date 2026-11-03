-- Operate on an existing disposable copy; never Save As or global calculate.
on run argv
 set filePath to item 1 of argv
 set fileName to item 2 of argv
 set actionName to item 3 of argv
 with timeout of 120 seconds
  tell application "Microsoft Excel"
   if exists workbook fileName then error "Target workbook is already open; refusing to change it"
   open POSIX file filePath
   set targetBook to workbook fileName
   set operationName to "open"
   try
    if actionName is "recalculate" then
     repeat with sheetIndex from 1 to count of worksheets of targetBook
      set operationName to "calculate worksheet " & sheetIndex
      calculate worksheet sheetIndex of targetBook
     end repeat
     set operationName to "save"
     save targetBook
    else if actionName is not "reopen" then
     error "Unsupported Excel action"
    end if
    set checkName to name of targetBook
    set operationName to "close"
    close targetBook saving no
    return checkName
   on error errorText number errorNumber
    try
     close targetBook saving no
    on error cleanupText
     log "Could not close run workbook: " & cleanupText
    end try
    error operationName & ": " & errorText number errorNumber
   end try
  end tell
 end timeout
end run
