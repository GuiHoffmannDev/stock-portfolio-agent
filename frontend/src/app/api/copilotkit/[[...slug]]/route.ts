import { HttpAgent } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";

const handler = createCopilotRuntimeHandler({
  runtime: new CopilotRuntime({
    agents: {
      default: new HttpAgent({
        url: process.env.NEXT_PUBLIC_CREWAI_URL ?? "http://127.0.0.1:8000/crewai-agent",
      }),
    },
  }),
  basePath: "/api/copilotkit",
});

export { handler as GET, handler as POST };
