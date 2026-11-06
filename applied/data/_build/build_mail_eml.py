"""メール（mail.json）を .eml にする。件名・宛名は RFC 2047、本文は UTF-8（8bit）。

Qwen（qwen3-coder:30b）が書いたものを、使っていない import を除いた以外はそのまま使っている。
"""
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import default
from email.utils import format_datetime

from lib_common import DATA, NOTICE, load_json

def build_one(mail: dict, by_id: dict) -> bytes:
    # Create EmailMessage with default policy
    msg = EmailMessage(policy=default)
    
    # Set From address
    from_addr = mail["from"]
    msg["From"] = Address(display_name=from_addr["name"], addr_spec=from_addr["email"])
    
    # Set To addresses
    to_addrs = []
    for addr in mail["to"]:
        to_addrs.append(Address(display_name=addr["name"], addr_spec=addr["email"]))
    msg["To"] = to_addrs
    
    # Set Cc addresses if exist
    cc_addrs = []
    for addr in mail["cc"]:
        cc_addrs.append(Address(display_name=addr["name"], addr_spec=addr["email"]))
    if cc_addrs:
        msg["Cc"] = cc_addrs
    
    # Set Subject
    msg["Subject"] = mail["subject"]
    
    # Set Date
    date_obj = datetime.fromisoformat(mail["date"])
    msg["Date"] = format_datetime(date_obj)
    
    # Set Message-ID
    msg_id = f"<{mail['id']}@synthetic.example>"
    msg["Message-ID"] = msg_id
    
    # Handle In-Reply-To and References
    in_reply_to = mail.get("in_reply_to")
    if in_reply_to:
        # Add In-Reply-To
        msg["In-Reply-To"] = f"<{in_reply_to}@synthetic.example>"
        
        # Collect references (following the chain)
        refs = []
        current_id = in_reply_to
        while current_id:
            refs.append(f"<{current_id}@synthetic.example>")
            if current_id in by_id:
                parent_id = by_id[current_id].get("in_reply_to")
                current_id = parent_id
            else:
                break
        # Add References (older first)
        msg["References"] = " ".join(reversed(refs))
    
    # Set additional header
    msg["X-Synthetic-Data"] = "true"
    
    # Process body text
    body_text = mail["body"]
    
    # Strip trailing whitespace and ensure it ends with a newline
    body_text = body_text.rstrip()
    if not body_text.endswith('\n'):
        body_text += '\n'
        
    # Add the notice footer
    expected_footer = f"（{NOTICE}）"
    if not body_text.strip().endswith(expected_footer):
        body_text += '\n' + expected_footer
    
    # Set content with correct charset and encoding
    msg.set_content(body_text, charset="utf-8", cte="8bit")
    
    # Return the raw bytes
    return msg.as_bytes()

def main():
    # Load mail data
    mail_data = load_json("mail.json")
    
    # Create output directory
    OUTPUT_DIR = DATA/"mail"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Build lookup table by id for references
    by_id = {m["id"]: m for m in mail_data["mails"]}
    
    # Iterate through all mails and build them
    for mail in mail_data["mails"]:
        # Generate output path based on the file name
        filename = mail.get("file")
        if not filename:
            filename = f"{mail['id']}.eml"
        
        # Build bytes for this email
        mail_bytes = build_one(mail, by_id)
        
        # Write to file
        out_path = OUTPUT_DIR/filename
        with open(out_path, 'wb') as f:
            f.write(mail_bytes)
        
        # Print the filename
        print(filename)

if __name__ == "__main__":
    main()
