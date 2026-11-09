"use client";

import {
  CopilotChat,
  CopilotKitProvider,
  useAgent,
  useDefaultRenderTool,
} from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { Suspense } from "react";

import { Panel, Portfolio, type PortfolioState } from "./portfolio";

function Workspace() {
  const { agent } = useAgent();
  // Shows each backend step (fetch_stock_data, calculate_allocations) as a card in the chat.
  useDefaultRenderTool();

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-rule px-4 py-2 text-xs tracking-wider uppercase">
        <span className="font-semibold text-accent">Stock Portfolio Agent</span>
        <span className="text-ink-dim">Portfolio research desk</span>
        <span role="status" className={`ml-auto ${agent.isRunning ? "text-up" : "text-ink-dim"}`}>
          ● {agent.isRunning ? "Agent running" : "Agent idle"}
        </span>
      </header>
      <div className="grid flex-1 gap-2 p-2 lg:grid-cols-[26rem_minmax(0,1fr)]">
        <Panel title="AI chat" className="h-[70dvh] lg:sticky lg:top-2 lg:h-[calc(100dvh-3.5rem)]">
          <div className="h-[calc(100%-2.25rem)]">
            <CopilotChat
              labels={{
                welcomeMessageText: "Which stocks do you hold, and how much did you invest in each?",
                chatInputPlaceholder: "Analyze AAPL and MSFT with $10k each",
              }}
            />
          </div>
        </Panel>
        <main className="min-w-0">
          <Portfolio state={agent.state as PortfolioState} running={agent.isRunning} />
        </main>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    // CopilotKit reads the clock while rendering, so it cannot be part of the static prerender.
    <Suspense fallback={null}>
      <CopilotKitProvider runtimeUrl="/api/copilotkit" enableInspector={false}>
        <Workspace />
      </CopilotKitProvider>
    </Suspense>
  );
}
