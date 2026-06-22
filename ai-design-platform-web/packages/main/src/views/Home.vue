<template>
  <div
    class="home-page bg-slate-950 min-h-screen flex items-center justify-center relative overflow-hidden"
  >
    <!-- Animated grid background -->
    <div
      class="absolute inset-0 bg-[linear-gradient(rgba(56,189,248,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(56,189,248,0.03)_1px,transparent_1px)] bg-[size:60px_60px] [mask-image:radial-gradient(ellipse_80%_60%_at_50%_40%,black_30%,transparent_70%)]"
    />

    <!-- Glow orbs -->
    <div class="absolute top-1/4 -left-32 w-96 h-96 bg-cyan-500/20 rounded-full blur-[128px]" />
    <div
      class="absolute bottom-1/4 -right-32 w-96 h-96 bg-purple-500/20 rounded-full blur-[128px]"
    />

    <div class="relative z-10 w-full max-w-5xl px-8">
      <div class="text-center mb-12">
        <h1 class="text-4xl font-bold text-white tracking-tight mb-3">AI Design Platform</h1>
        <p class="text-slate-400 text-lg">智能设计，无限可能</p>
      </div>

      <div class="grid grid-cols-3 gap-6">
        <!-- AI Chat -->
        <router-link
          to="/ai-chat"
          class="group relative block rounded-2xl border border-slate-700/50 bg-slate-900/60 backdrop-blur-sm p-8 hover:border-cyan-500/50 hover:bg-slate-900/80 transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_0_40px_rgba(6,182,212,0.15)]"
        >
          <div
            class="absolute inset-0 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"
          />
          <div class="relative">
            <div
              class="w-14 h-14 rounded-xl bg-cyan-500/20 flex items-center justify-center mb-5 group-hover:bg-cyan-500/30 transition-colors"
            >
              <span class="text-2xl">💬</span>
            </div>
            <h3 class="text-xl font-semibold text-white mb-2">AI 对话</h3>
            <p class="text-slate-400 text-sm leading-relaxed">
              智能对话引擎，自然语言交互，多轮上下文理解
            </p>
            <div
              class="mt-5 flex items-center text-cyan-400 text-sm font-medium opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            >
              进入模块
              <svg
                class="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M13 7l5 5m0 0l-5 5m5-5H6"
                />
              </svg>
            </div>
          </div>
        </router-link>

        <!-- AI Generation -->
        <router-link
          to="/ai-generation"
          class="group relative block rounded-2xl border border-slate-700/50 bg-slate-900/60 backdrop-blur-sm p-8 hover:border-emerald-500/50 hover:bg-slate-900/80 transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_0_40px_rgba(16,185,129,0.15)]"
        >
          <div
            class="absolute inset-0 rounded-2xl bg-gradient-to-br from-emerald-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"
          />
          <div class="relative">
            <div
              class="w-14 h-14 rounded-xl bg-emerald-500/20 flex items-center justify-center mb-5 group-hover:bg-emerald-500/30 transition-colors"
            >
              <span class="text-2xl">🎨</span>
            </div>
            <h3 class="text-xl font-semibold text-white mb-2">AI 生成</h3>
            <p class="text-slate-400 text-sm leading-relaxed">
              内容创意生成，图像智能创作，多模态输出
            </p>
            <div
              class="mt-5 flex items-center text-emerald-400 text-sm font-medium opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            >
              进入模块
              <svg
                class="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M13 7l5 5m0 0l-5 5m5-5H6"
                />
              </svg>
            </div>
          </div>
        </router-link>

        <!-- AI Workflow -->
        <router-link
          to="/ai-workflow"
          class="group relative block rounded-2xl border border-slate-700/50 bg-slate-900/60 backdrop-blur-sm p-8 hover:border-purple-500/50 hover:bg-slate-900/80 transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_0_40px_rgba(168,85,247,0.15)]"
        >
          <div
            class="absolute inset-0 rounded-2xl bg-gradient-to-br from-purple-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"
          />
          <div class="relative">
            <div
              class="w-14 h-14 rounded-xl bg-purple-500/20 flex items-center justify-center mb-5 group-hover:bg-purple-500/30 transition-colors"
            >
              <span class="text-2xl">⚡</span>
            </div>
            <h3 class="text-xl font-semibold text-white mb-2">AI 工作流</h3>
            <p class="text-slate-400 text-sm leading-relaxed">
              可视化工作流编排，自动化任务调度，智能决策链路
            </p>
            <div
              class="mt-5 flex items-center text-purple-400 text-sm font-medium opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            >
              进入模块
              <svg
                class="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M13 7l5 5m0 0l-5 5m5-5H6"
                />
              </svg>
            </div>
          </div>
        </router-link>
      </div>
    </div>
  </div>
</template>
