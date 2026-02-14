function fetchMissAvDetailsCheckExist_V2() {
    Logger.log("Starting fetchMissAvDetailsCheckExist_V2...");

    // 1. Fetch ALL existing Items (to check against)
    // We need to know which MovieCodes already exist in our library.
    const existItems = Me.Items.where(r => r.Id !== '' && r.MovieCode !== '').all();
    const existingMovieCodes = new Set(existItems.map(item => item.MovieCode));
    Logger.log(`Found ${existItems.length} existing items in library.`);

    // 2. Fetch rows from 'fetchMissAvRemote' that need checking
    // Criteria: detailsUrl is present, movieCode is present, and isFile? is not already TRUE (or empty).
    // Note: The original code checked for (r['isFile?'] === '' || r['isFile?'] === false).
    // We'll stick to that logic logic or just fetch all candidate rows. 
    // Let's optimize by fetching those that *might* need updating.
    // Actually, to be safe and consistent with V1, we should check everything that fits the criteria.
    const fetchRows = Me.FetchMissAvRemote.where(r => r.detailsUrl !== '' && r.movieCode !== '' && (r['isFile?'] === '' || r['isFile?'] === false)).all();
    Logger.log(`Found ${fetchRows.length} rows to check in fetchMissAvRemote.`);

    if (fetchRows.length === 0) {
        Logger.log("No rows to process. Exiting.");
        return;
    }

    // 3. Get proper Sheet Objects to map 'detailsUrl' -> 'row_'
    // Because 'update' mode in Sheet.writeToSheet_V2 requires the 'row_' property.
    // Tamotsu objects don't natively expose the sheet row number in a way we can rely on for this bulk update method without re-fetching.
    // So we fetch the entire sheet data as objects to get the row numbers.
    const allSheetRows = Sheet.getSheetObjects('fetchMissAvRemote');

    // Create a map: detailsUrl -> row_
    // We assume 'detailsUrl' is unique as per config.js
    const urlToRowMap = new Map();
    allSheetRows.forEach(row => {
        if (row.detailsUrl) {
            urlToRowMap.set(row.detailsUrl, row.row_);
        }
    });

    // 4. Prepare Batch Updates
    const updates = [];
    let updateCount = 0;

    fetchRows.forEach(tamotsuRow => {
        const movieCode = tamotsuRow.movieCode;
        const detailsUrl = tamotsuRow.detailsUrl;

        // Check if this movie exists in our library
        const exists = existingMovieCodes.has(movieCode);

        // Only queue an update if the value is actually changing or needs to be set
        // The query filtered for isFile? == '' or false.
        // So if exists is TRUE, we definitely update.
        // If exists is FALSE, and it was already false, strictly speaking we don't *need* to write, 
        // but the original code did `row['isFile?'] = existingMovieCodes.has(row.movieCode); row.save()` for ALL fetched.
        // So it essentially confirmed the 'false' state as well.
        // Let's stick to updating everything we fetched to ensure consistency.

        const rowNumber = urlToRowMap.get(detailsUrl);

        if (rowNumber) {
            updates.push({
                'row_': rowNumber,
                'isFile?': exists
            });
            updateCount++;
        } else {
            // This shouldn't happen if the row was just fetched from Tamotsu, unless the sheet changed uniquely fast or duplicate URLs exist.
            Logger.log(`Warning: Could not find row number for URL: ${detailsUrl}`);
        }
    });

    // 5. Execute Batch Write
    if (updates.length > 0) {
        Logger.log(`Writing ${updates.length} updates to sheet...`);
        Sheet.writeToSheet_V2('fetchMissAvRemote', updates, 'update');
        Logger.log("Batch write complete.");
    } else {
        Logger.log("No matching rows found to update in the sheet map.");
    }
}
