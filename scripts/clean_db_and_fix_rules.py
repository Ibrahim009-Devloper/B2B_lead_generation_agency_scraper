import sqlite3

conn = sqlite3.connect("lead_gen.db")
c = conn.cursor()

# 1. Delete Signalflow test leads
c.execute("DELETE FROM leads WHERE website LIKE '%signalflow%'")
deleted_leads = c.rowcount
c.execute("DELETE FROM scraped_domains WHERE domain LIKE '%signalflow%'")
deleted_domains = c.rowcount

# 2. Demote any leads where both email and phone are missing from Hot Lead to Needs Review
c.execute("""
    UPDATE leads 
    SET overall_priority = 'Needs Review',
        rejection_reason = 'Demoted: Missing actionable contact channel (no verified email or phone found).'
    WHERE overall_priority = 'Hot Lead' AND (verified_email IS NULL OR verified_email = '') AND (phone IS NULL OR phone = '')
""")
demoted_hot = c.rowcount

# 3. Fix blog title business names in leads
c.execute("""
    UPDATE leads
    SET business_name = 'Outreach Monks'
    WHERE website = 'outreachmonks.com' AND business_name LIKE '%5 best%'
""")
updated_names = c.rowcount

conn.commit()
conn.close()
print(f"Deleted SignalFlow: {deleted_leads} leads, {deleted_domains} domains")
print(f"Demoted invalid Hot Leads without contact: {demoted_hot}")
print(f"Fixed blog names: {updated_names}")

