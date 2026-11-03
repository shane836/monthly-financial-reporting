// JXA bridge to the already authenticated configured account in Apple Mail.
// No credentials or token extraction. Input/output are JSON files/stdout.
ObjC.import('Foundation');
function readJSON(path) {
  const content = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null);
  if (!content) throw Error('Cannot read request file');
  return JSON.parse(ObjC.unwrap(content));
}
function run(argv) {
  const req = readJSON(argv[0]);
  const app = Application('Mail');
  const matches = app.accounts().filter(a => a.emailAddresses().some(e => e.toLowerCase() === req.mailbox.toLowerCase()));
  if (matches.length !== 1) throw Error('Configured mailbox missing or ambiguous in Apple Mail');
  const account = matches[0];
  if (!account.enabled()) throw Error('Configured mailbox is disabled');
  if(req.action==='refresh') {
    app.checkForNewMail({for:account});
    return JSON.stringify({refresh_requested:true});
  }
  const boxes = [];
  function collect(parent) {
    for (const box of parent.mailboxes()) { boxes.push(box); collect(box); }
  }
  collect(account);
  function metadata(m, box) {
    return {id:m.id(), internet_message_id:m.messageId(), mailbox:box.name(), subject:m.subject(), sender:m.sender(), recipients:m.toRecipients().map(r=>r.address()), received_at:m.dateReceived().toISOString(), attachments:m.mailAttachments().map((a,i)=>({index:i,name:a.name(),size:a.fileSize(),downloaded:a.downloaded()}))};
  }
  if (req.action === 'status') return JSON.stringify({account:account.name(),email_addresses:account.emailAddresses(),enabled:account.enabled(),mailboxes:boxes.map(b=>b.name())});
  if (req.action === 'search') {
    const result=[],seen=new Set();
    for (const box of boxes) {
      if (req.sent_only && box.name() !== 'Sent Items' && box.name() !== 'Sent') continue;
      if (req.exclude_sent && ['Sent Items','Sent','Drafts','Outbox','Deleted Items','Trash','Junk Email','Junk'].includes(box.name())) continue;
      let query={subject:{_contains:req.query}};
      if(req.since) query={_and:[query,{dateReceived:{_greaterThan:new Date(req.since)}}]};
      for (const m of box.messages.whose(query)()) {
        if(req.contains_body && !m.content().includes(req.contains_body)) continue;
        if(!seen.has(m.id())) { result.push(metadata(m,box)); seen.add(m.id()); }
      }
    }
    return JSON.stringify(result);
  }
  if (req.action === 'download') {
    const found=[],seen=new Set();
    for (const box of boxes) for(const m of box.messages.whose({id:req.id})()) {
      if(!seen.has(m.id())) {found.push(m);seen.add(m.id());}
    }
    if(found.length!==1) throw Error('Mail message missing or ambiguous');
    const att=found[0].mailAttachments()[req.attachment_index];
    if(!att || att.name()!==req.filename) throw Error('Attachment identity changed');
    app.save(att,{in:Path(req.path)});
    return JSON.stringify({saved:req.path,message_id:found[0].messageId()});
  }
  if (req.action === 'send') {
    if(req.approved !== true || !Array.isArray(req.allowed_recipients) || !req.allowed_recipients.includes(req.to.toLowerCase())) throw Error('Recipient or approval not authorized');
    const m=app.OutgoingMessage({subject:req.subject,content:req.body+'\n',visible:false,sender:req.mailbox});
    app.outgoingMessages.push(m);
    m.toRecipients.push(app.ToRecipient({address:req.to}));
    for (const path of (req.attachments || [])) m.content.attachments.push(app.Attachment({fileName:Path(path)}));
    const accepted=app.send(m);
    if(!accepted) throw Error('Apple Mail did not accept the send');
    return JSON.stringify({submitted:true});
  }
  throw Error('Unsupported Mail action');
}
