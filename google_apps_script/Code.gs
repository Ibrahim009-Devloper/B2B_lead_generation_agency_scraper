/**
 * Google Apps Script Webhook Handler for B2B Lead Gen Pipeline
 * 
 * Target Sheet: https://docs.google.com/spreadsheets/d/1yM7NdHxgcEVECEeGNevnXLsVtt_Fcu1fF-yJnSc5GSA/edit?gid=0#gid=0
 * 
 * Deployment Instructions:
 * 1. Open the Google Sheet above.
 * 2. Click "Extensions" -> "Apps Script".
 * 3. Replace all existing code with this script.
 * 4. Click "Deploy" -> "New deployment".
 * 5. Select type: "Web app".
 * 6. Description: "Lead Gen Ingestion Webhook".
 * 7. Execute as: "Me" (your email).
 * 8. Who has access: "Anyone" (crucial for webhook POSTs without OAuth).
 * 9. Click "Deploy", copy the "Web app URL" (ends with /exec), and save it as GOOGLE_SHEET_WEBHOOK_URL in .env.
 */

function doPost(e) {
  var lock = LockService.getScriptLock();
  // Wait up to 10 seconds for other concurrent writes
  var success = lock.tryLock(10000);
  if (!success) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: "Sheet lock timeout - another batch is writing"
    })).setMimeType(ContentService.MimeType.JSON);
  }

  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

    // Auto-create 12-column header row if sheet is brand new / empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow([
        "Company Name",
        "Website Domain",
        "Verification Status",
        "Primary Verified Email",
        "Email Category",
        "Backup Emails",
        "Decision Maker Name & Role",
        "Complete Business Summary",
        "Their Target Clients",
        "How to Pitch / Personalization Guide",
        "Ready Personalized Cold Email",
        "Source Footprint",
        "Ingested At"
      ]);
      // Format header row bold with background
      sheet.getRange(1, 1, 1, 13).setFontWeight("bold").setBackground("#e8f0fe");
      sheet.setFrozenRows(1);
    }

    if (!e || !e.postData || !e.postData.contents) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "error",
        message: "No post data received"
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var data = JSON.parse(e.postData.contents);
    var leads = data.leads || (Array.isArray(data) ? data : [data]);
    var rows = [];

    for (var i = 0; i < leads.length; i++) {
      var item = leads[i];
      var backupStr = "";
      if (Array.isArray(item.backup_emails)) {
        backupStr = item.backup_emails.join(", ");
      } else if (item.backup_emails) {
        backupStr = String(item.backup_emails);
      }

      rows.push([
        item.company_name || "",
        item.website_domain || "",
        item.verification_status || "",
        item.primary_email || "",
        item.email_category || "",
        backupStr,
        item.decision_maker || "",
        item.business_summary || "",
        item.target_clients || "",
        item.pitch_guide || "",
        item.cold_email || "",
        item.source_footprint || "",
        new Date().toISOString()
      ]);
    }

    if (rows.length > 0) {
      var startRow = sheet.getLastRow() + 1;
      sheet.getRange(startRow, 1, rows.length, rows[0].length).setValues(rows);
    }

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      appended_count: rows.length
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: "ok",
    message: "Google Apps Script Lead Webhook is active and listening for POST requests."
  })).setMimeType(ContentService.MimeType.JSON);
}

