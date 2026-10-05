import {
  describeIdentity,
  formatAccountLabel,
  splitFileTail,
  UNKNOWN_COUNTERPARTY,
} from "../lib/identity";

export function UserLabel({
  value,
  kind = "identity",
}: {
  value: string;
  kind?: "identity" | "account" | "file";
}) {
  if (kind === "account") {
    const shown = formatAccountLabel(value);
    return (
      <span className="user-label" dir="auto" title={value}>
        {shown}
      </span>
    );
  }

  if (kind === "file") {
    const tail = splitFileTail(value);
    if (tail === null) {
      return (
        <span className="user-label" dir="auto" title={value}>
          {value.trim()}
        </span>
      );
    }
    return <SplitLabel title={value} lead={tail.lead} tail={tail.tail} />;
  }

  const shape = describeIdentity(value);
  if (shape.kind === "empty") {
    return (
      <span
        className="user-label is-unknown"
        dir="auto"
        title={UNKNOWN_COUNTERPARTY}
      >
        {UNKNOWN_COUNTERPARTY}
      </span>
    );
  }
  if (shape.kind === "email") {
    return (
      <SplitLabel title={value} lead={shape.local} tail={`@${shape.domain}`} />
    );
  }
  if (shape.kind === "file") {
    return (
      <SplitLabel title={value} lead={shape.stem} tail={`.${shape.ext}`} />
    );
  }
  return (
    <span className="user-label" dir="auto" title={value}>
      {shape.text}
    </span>
  );
}

function SplitLabel({
  title,
  lead,
  tail,
}: {
  title: string;
  lead: string;
  tail: string;
}) {
  return (
    <span className="user-label is-split" dir="auto" title={title}>
      <span className="user-label-lead">{lead}</span>
      <span className="user-label-tail">{tail}</span>
    </span>
  );
}
