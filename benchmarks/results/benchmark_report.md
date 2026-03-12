# RepoGraph Benchmark Report

Source: `C:\Users\ssamu\OneDrive\Desktop\RepoGraphAI\benchmarks\results\benchmark_results.json`

**Agent Comparison (brian)**
| query | baseline_tokens | repograph_tokens | token_reduction | read_time_reduction | arch_time_s | conn_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| explain login | 5081 | 23377 | -3.6009 | -2.8814 | 1.3631 | 1.3847 |
| explain clock | 120798 | 105299 | 0.1283 | 0.0708 | 1.3558 | 1.4064 |
| explain function run | 98683 | 319514 | -2.2378 | -2.2381 | 1.3501 | 1.4657 |

![Agent Token Reduction brian](C:/Users/ssamu/OneDrive/Desktop/RepoGraphAI/benchmarks/results/agent_token_reduction_brian.svg)

![Agent Read Time Reduction brian](C:/Users/ssamu/OneDrive/Desktop/RepoGraphAI/benchmarks/results/agent_read_time_reduction_brian.svg)

![Agent CLI Time brian](C:/Users/ssamu/OneDrive/Desktop/RepoGraphAI/benchmarks/results/agent_cli_time_brian.svg)

**Gemini Agent Comparison (Real Model)**
Source: `C:\Users\ssamu\OneDrive\Desktop\RepoGraphAI\benchmarks\results\gemini_agent_results.json`

**Gemini (brian)**
| query | baseline_prompt_tokens | repograph_prompt_tokens | baseline_files | repograph_files |
| --- | --- | --- | --- | --- |
| explain login | 7935 | 27281 | 8 | 6 |
| explain clock | 82512 | 55449 | 5 | 6 |
| explain function run | 84532 | 94655 | 6 | 21 |

![Gemini Baseline Tokens brian](C:/Users/ssamu/OneDrive/Desktop/RepoGraphAI/benchmarks/results/gemini_baseline_tokens_brian.svg)

![Gemini RepoGraph Tokens brian](C:/Users/ssamu/OneDrive/Desktop/RepoGraphAI/benchmarks/results/gemini_repograph_tokens_brian.svg)
