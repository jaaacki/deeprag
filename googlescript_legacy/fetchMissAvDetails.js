function fetchMissAvDetailsCheckExist() {
  const existItems = Me.Items.where(r => r.Id !== '' && r.MovieCode !== '').all()
  const fetchRows = Me.FetchMissAvRemote.where(r => r.detailsUrl !== '' && r.movieCode !== '' && (r['isFile?'] === '' || r['isFile?'] === false)).all()
  Logger.log(fetchRows.length)

  // Create a Set of existing movie codes for efficient lookup
  const existingMovieCodes = new Set(existItems.map(item => item.MovieCode));

  // Loop through each fetchRow and check if it exists
  fetchRows.forEach(row => {
    row['isFile?'] = existingMovieCodes.has(row.movieCode);
    row.save();
  });

  Logger.log(`Processed ${fetchRows.length} rows`);
}

function fetchMissAvDetails() {
  const rows = Me.FetchMissAvRemote.where(row => {
    return row.detailsUrl !== '' && (row['processed?'] === '' || row['processed?'] === false)
  }
  ).all()
  // Logger.log(rows)

  const searchTerms = ['english', 'chinese', 'uncensored'];
  const extractAndFormatMatches = function (url, searchTerms) {
    const lowerUrl = url.toLowerCase();
    const foundMatches = searchTerms.filter(term => {
      return lowerUrl.includes(term.toLowerCase());
    });
    const formattedString = foundMatches.map(term => {
      return term.charAt(0).toUpperCase() + term.slice(1).toLowerCase();
    }).join(', ');

    return formattedString;
  }

  const extractIdFromUrl = (urlString) => {
    if (!urlString) return null;
    const segments = urlString.split('/').filter(Boolean);
    const lastSegment = segments.pop();

    const match = lastSegment.match(/([a-z]{2,6}-\d+)/i);
    return match ? match[0].toUpperCase() : null;
  }

  rows.forEach(r => {
    const result = getMissAvDetails(r.detailsUrl);
    const meta = extractAndFormatMatches(r.detailsUrl, searchTerms)
    const artistString = (result.actress || []).join(', ');
    // Logger.log(artistString)
    // Logger.log(JSON.stringify(result))
    r['processed?'] = true
    r['movieCode'] = extractIdFromUrl(r.detailsUrl)
    r['artist'] = artistString
    r['meta'] = meta
    r.save()
    Logger.log(result)
  })
}

function getNewScoutMissAv(url) {
  const existItems = Me.Items.where(r => r.Id !== '' && r.MovieCode !== '').all()
  const existFetch = Me.FetchMissAvRemote.where(r => r.detailsUrl !== '' && r.movieCode !== '').all()

  const result = scoutMissAv(url);
  Logger.log(result)

  // Create a Set of existing movie codes from both sources for efficient lookup
  const existingMovieCodes = new Set([
    ...existItems.map(item => item.MovieCode),
    ...existFetch.map(item => item.movieCode)
  ]);

  // Filter out links where movieCode already exists in either existItems or existFetch
  const newLinks = result.links.filter(link => !existingMovieCodes.has(link.movieCode));

  // Logger.log(JSON.stringify(newLinks))
  return newLinks; // This returns an array of objects, each containing name, url, and movieCode
}

function scoutNewUrls() {
  const newUrl = Me.ScoutList.where(r => r.url !== '' && (r['processed?'] === '' || r['processed?'] === false)).first()

  // Early exit if nothing to do
  if (!newUrl) {
    console.log("No unprocessed URLs found.");
    return;
  }

  Logger.log("Processing: " + newUrl.url)

  let finalLinkCount = 0;
  let processComment = ""; // Variable to store our message

  try {
    // --- ATTEMPT TO FETCH ---
    const newLinks = getNewScoutMissAv(newUrl.url)

    // Check if we actually got an array back
    if (newLinks && newLinks.length > 0) {

      // --- PROCESS LINKS logic ---
      const bestByMovieCode = {}

      for (var i = 0; i < newLinks.length; i++) {
        const link = newLinks[i]
        if (!link || !link.movieCode || !link.url) continue

        const movieCode = link.movieCode
        const url = link.url

        const obj = {
          detailsUrl: url,
          movieCode: movieCode,
          'processed?': false,
          'isFile?': false
        }

        if (!bestByMovieCode[movieCode]) {
          bestByMovieCode[movieCode] = obj
        } else {
          const existing = bestByMovieCode[movieCode]
          if (ScoutMissAv && ScoutMissAv.isBetterUrl(url, existing.detailsUrl)) {
            bestByMovieCode[movieCode] = obj
          }
        }
      }

      const newArray = Object.keys(bestByMovieCode).map(function (k) { return bestByMovieCode[k] })

      // --- WRITE TO SHEET ---
      if (newArray.length > 0) {
        Sheet.writeToSheet('fetchMissAvRemote', newArray, 'append')
        finalLinkCount = newArray.length;
        processComment = "Success: Added " + finalLinkCount + " new unique links.";
      } else {
        processComment = "Scanned, but filtered out duplicates (0 added).";
      }

    } else {
      // Case: getNewScoutMissAv returned empty array
      processComment = "Scanned, but source returned 0 links.";
    }

  } catch (e) {
    // --- CATCH ERRORS ---
    // If getNewScoutMissAv fails (network error, parsing error), code jumps here.
    Logger.log("Error: " + e.message);
    processComment = "Failed: " + e.message;
    finalLinkCount = 0;
  }

  // --- FINAL SAVE (Always runs) ---
  // We update the row regardless of success or failure so it doesn't get stuck.
  Logger.log("Result: " + processComment);

  newUrl.linkCount = finalLinkCount;
  newUrl['processed?'] = true;
  newUrl.comment = processComment; // Write the message to the column
  newUrl.save();

  /** fetch missAv Details */
  fetchMissAvDetails()
}

const ScoutMissAv = {
  isBetterUrl: function (candidateUrl, existingUrl) {
    const rank = function (url) {
      const lower = (url || '').toLowerCase()
      if (lower.indexOf('english') !== -1) return 3
      if (lower.indexOf('chinese') !== -1) return 2
      return 1
    }

    const cRank = rank(candidateUrl)
    const eRank = rank(existingUrl)

    if (cRank !== eRank) return cRank > eRank
    return (candidateUrl || '').length > (existingUrl || '').length
  }
}
