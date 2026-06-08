import { useCallback } from "react";
import { coloniesApi } from "@/api/colonies";
import ToolsEditor from "./ToolsEditor";

export default function ColonyToolsSection({
  colonyName,
}: {
  colonyName: string;
}) {
  const fetchSnapshot = useCallback(
    () => coloniesApi.getTools(colonyName),
    [colonyName],
  );
  const saveAllowlist = useCallback(
    (enabled: string[] | null) => coloniesApi.updateTools(colonyName, enabled),
    [colonyName],
  );
  return (
    <ToolsEditor
      subjectKey={`colony:${colonyName}`}
      title="Tools"
      caveat="Changes apply to the next worker spawn. Running workers keep the tool list they booted with."
      fetchSnapshot={fetchSnapshot}
      saveAllowlist={saveAllowlist}
    />
  );
}
