function handleEdit(e) {
  if (!e) return;

  const sheet = e.source.getActiveSheet();
  
  // 1. CHECK SHEET NAME FIRST
  // If it's not "scoutLists", we stop immediately.
  if (sheet.getName() !== "scoutLists") return;

  const range = e.range;
  const col = range.getColumn();
  const lastCol = range.getLastColumn();

  // 2. CHECK COLUMN (Optimization)
  // We only proceed if the edit involves Column B (Col 2)
  // This prevents the script from running if you edit Column Z.
  if (col <= 2 && lastCol >= 2) {
    Sheet.processRowsForIds(sheet, range);
  }
}