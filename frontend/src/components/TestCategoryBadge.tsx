import type { ReactNode } from "react";
import { CircleCheck, CircleX, Zap } from "lucide-react";
import type { TestCategory } from "@/api/client";
import { Badge, type BadgeProps } from "@/components/ui/badge";

const CATEGORY_VARIANT: Record<TestCategory, BadgeProps["variant"]> = {
  POSITIVE: "success",
  NEGATIVE: "danger",
  EDGE: "violet",
};

const CATEGORY_ICON: Record<TestCategory, ReactNode> = {
  POSITIVE: <CircleCheck />,
  NEGATIVE: <CircleX />,
  EDGE: <Zap />,
};

export function TestCategoryBadge({ category }: { category: TestCategory }) {
  return (
    <Badge variant={CATEGORY_VARIANT[category]} icon={CATEGORY_ICON[category]} className="font-mono">
      {category}
    </Badge>
  );
}
