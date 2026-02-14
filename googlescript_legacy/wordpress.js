/**
 * Refreshes the WordPress token using the refresh token
 * @returns {string} Success or error message
 */
function refreshWordPressToken() {
  try {
    // Call WordPress service to refresh token
    const response = WordPressService.refreshToken();

    if (!response.success) {
      throw new Error(`Token refresh failed: ${response.error}`);
    }

    const data = response.data;

    // Check if we got a new access token
    if (!data.access_token) {
      throw new Error('No access token received in response');
    }

    // Store the new access token in script properties
    PropertiesService.getScriptProperties().setProperty('wp_token', data.access_token);

    // Log token expiration info if provided
    if (data.expires_in) {
      Logger.log(`New token expires in ${data.expires_in} seconds`);
    }

    Logger.log('WordPress token refreshed successfully');
    return 'Success: WordPress token refreshed';

  } catch (error) {
    Logger.log(`Error refreshing WordPress token: ${error.toString()}`);
    throw new Error(`Failed to refresh WordPress token: ${error.toString()}`);
  }
}

/**
 * Search for content using WordPress MissAV search
 * @param {string} moviecode - The movie code to search for
 * @returns {object} Search results
 */
function searchMissAv(moviecode) {
  try {
    if (!moviecode) {
      throw new Error('Movie code is required');
    }

    const response = WordPressService.missavSearch(moviecode);

    if (!response.success) {
      // Try refreshing token if unauthorized
      if (response.statusCode === 401) {
        Logger.log('Token expired, attempting to refresh...');
        refreshWordPressToken();

        // Retry the search with new token
        const retryResponse = WordPressService.missavSearch(moviecode);
        if (!retryResponse.success) {
          throw new Error(`Search failed after token refresh: ${retryResponse.error}`);
        }
        return retryResponse.data;
      }

      throw new Error(`Search failed: ${response.error}`);
    }
    Logger.log(response.data)
    return response.data;

  } catch (error) {
    Logger.log(`Error in searchMissAv: ${error.toString()}`);
    throw new Error(`Failed to search MissAv: ${error.toString()}`);
  }
}

/** Scout MissAv */
function scoutMissAv(url) {
  try {
    if (!url) {
      throw new Error('URL is required');
    }

    const response = WordPressService.scoutMissAv(url);

    if (!response.success) {
      // Try refreshing token if unauthorized
      if (response.statusCode === 401) {
        Logger.log('Token expired, attempting to refresh...');
        refreshWordPressToken();

        // Retry the request with new token
        const retryResponse = WordPressService.scoutMissAv(url);
        if (!retryResponse.success) {
          throw new Error(`Details fetch failed after token refresh: ${retryResponse.error}`);
        }
        return retryResponse.data;
      }

      throw new Error(`Details fetch failed: ${response.error}`);
    }

    return response.data;

  } catch (error) {
    Logger.log(`Error in scoutMissAv: ${error.toString()}`);
    throw new Error(`Failed to get scoutMissAv details: ${error.toString()}`);
  }
}

/**
 * Get details for content using WordPress MissAV details
 * @param {string} url - The MissAV URL
 * @returns {object} Content details
 */
function getMissAvDetails(url) {
  try {
    if (!url) {
      throw new Error('URL is required');
    }

    const response = WordPressService.missavDetails(url);

    if (!response.success) {
      // Try refreshing token if unauthorized
      if (response.statusCode === 401) {
        Logger.log('Token expired, attempting to refresh...');
        refreshWordPressToken();

        // Retry the request with new token
        const retryResponse = WordPressService.missavDetails(url);
        if (!retryResponse.success) {
          throw new Error(`Details fetch failed after token refresh: ${retryResponse.error}`);
        }
        return retryResponse.data;
      }

      throw new Error(`Details fetch failed: ${response.error}`);
    }

    return response.data;

  } catch (error) {
    Logger.log(`Error in getMissAvDetails: ${error.toString()}`);
    throw new Error(`Failed to get MissAv details: ${error.toString()}`);
  }
}

/**
 * Process items sheet and populate MissAV data for items with empty missAv_status
 * @returns {string} Success or error message
 */
function getMissAvDataToRemove() {
  try {
    // Get the spreadsheet
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

    // Get items sheet
    const itemsSheet = spreadsheet.getSheetByName('items');
    if (!itemsSheet) {
      throw new Error('items sheet not found. Please run getChildItems() first.');
    }

    // Get all data from items sheet
    const lastRow = itemsSheet.getLastRow();
    if (lastRow <= 1) {
      throw new Error('No data found in items sheet.');
    }

    // Get headers to find column indices
    const headers = itemsSheet.getRange(1, 1, 1, itemsSheet.getLastColumn()).getValues()[0];
    const columnMap = {};
    headers.forEach((header, index) => {
      columnMap[header] = index + 1;
    });

    // Get all items data
    const itemsData = itemsSheet.getRange(2, 1, lastRow - 1, itemsSheet.getLastColumn()).getValues();

    let processedCount = 0;
    let errorCount = 0;

    // Process each item that needs MissAV data (where missAv_status is empty)
    for (let i = 0; i < itemsData.length; i++) {
      const rowIndex = i + 2; // Actual row number in sheet
      const movieCode = itemsData[i][columnMap['MovieCode'] - 1];
      const missAvStatus = itemsData[i][columnMap['missAv_status'] - 1];

      // Skip if missAv_status is not empty (except for "error" status) or MovieCode is empty/invalid
      if (missAvStatus && missAvStatus !== 'error' || !movieCode || movieCode === '-' || movieCode.toString().trim() === '') {
        continue;
      }

      try {
        // Search using the MovieCode
        const searchResult = searchMissAv(movieCode);

        const updates = [];

        if (searchResult.success && searchResult.data && Object.keys(searchResult.data).length > 0) {
          // Success - populate all fields
          updates.push([rowIndex, columnMap['missAv_status'], 'completed']);

          if (searchResult.data.movie_code && columnMap['missAv_movie_code']) {
            updates.push([rowIndex, columnMap['missAv_movie_code'], searchResult.data.movie_code]);
          }

          if (searchResult.data.title && columnMap['missAv_title']) {
            updates.push([rowIndex, columnMap['missAv_title'], searchResult.data.title]);
          }

          if (searchResult.data.raw_image_url && columnMap['missAv_raw_image_url']) {
            updates.push([rowIndex, columnMap['missAv_raw_image_url'], searchResult.data.raw_image_url]);
          }

          if (searchResult.data.image_cropped && columnMap['missAv_image_cropped']) {
            updates.push([rowIndex, columnMap['missAv_image_cropped'], searchResult.data.image_cropped]);
          }

          if (searchResult.data.overview && columnMap['missAv_overview']) {
            updates.push([rowIndex, columnMap['missAv_overview'], searchResult.data.overview]);
          }

          if (searchResult.data.release_date && columnMap['missAv_release_date']) {
            updates.push([rowIndex, columnMap['missAv_release_date'], searchResult.data.release_date]);
          }

          if (searchResult.data.original_title && columnMap['missAv_original_title']) {
            updates.push([rowIndex, columnMap['missAv_original_title'], searchResult.data.original_title]);
          }

          if (searchResult.data.actress && columnMap['missAv_actress']) {
            const actressString = Array.isArray(searchResult.data.actress) ? searchResult.data.actress.join(', ') : searchResult.data.actress;
            updates.push([rowIndex, columnMap['missAv_actress'], actressString]);
          }

          if (searchResult.data.genre && columnMap['missAv_genre']) {
            const genreString = Array.isArray(searchResult.data.genre) ? searchResult.data.genre.join(', ') : searchResult.data.genre;
            updates.push([rowIndex, columnMap['missAv_genre'], genreString]);
          }

          if (searchResult.data.series && columnMap['missAv_series']) {
            updates.push([rowIndex, columnMap['missAv_series'], searchResult.data.series]);
          }

          if (searchResult.data.maker && columnMap['missAv_maker']) {
            updates.push([rowIndex, columnMap['missAv_maker'], searchResult.data.maker]);
          }

          if (searchResult.data.label && columnMap['missAv_label']) {
            updates.push([rowIndex, columnMap['missAv_label'], searchResult.data.label]);
          }
          if (searchResult.data.label && columnMap['missAv_source_url']) {
            updates.push([rowIndex, columnMap['missAv_source_url'], searchResult.data.source_url]);
          }

        } else {
          // No result found
          updates.push([rowIndex, columnMap['missAv_status'], 'no result']);
        }

        // Apply all updates to the sheet
        updates.forEach(update => {
          itemsSheet.getRange(update[0], update[1]).setValue(update[2]);
        });

        processedCount++;
        Logger.log(`Processed item ${movieCode}: ${searchResult.success ? 'found' : 'no result'}`);

        // Add a small delay to avoid hitting API rate limits
        Utilities.sleep(500);

      } catch (apiError) {
        Logger.log(`Error processing MissAV data for ${movieCode}: ${apiError.toString()}`);
        // Mark as error in status
        itemsSheet.getRange(rowIndex, columnMap['missAv_status']).setValue('error');
        errorCount++;
      }
    }

    Logger.log(`Successfully processed ${processedCount} items, ${errorCount} errors`);
    return `Success: Processed ${processedCount} items with MissAV data (${errorCount} errors)`;

  } catch (error) {
    Logger.log(`Error in processMissAvData: ${error.toString()}`);
    throw new Error(`Failed to process MissAV data: ${error.toString()}`);
  }
}
