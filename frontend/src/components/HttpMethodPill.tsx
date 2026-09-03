import type { HttpMethod } from "@/api/client";
import { Badge, type BadgeProps } from "@/components/ui/badge";

const METHOD_VARIANT: Record<HttpMethod, BadgeProps["variant"]> = {
  GET: "info",
  POST: "success",
  PUT: "warning",
  PATCH: "violet",
  DELETE: "danger",
};

export function HttpMethodPill({ method }: { method: HttpMethod }) {
  return (
    <Badge variant={METHOD_VARIANT[method]} className="font-mono rounded-md">
      {method}
    </Badge>
  );
}
