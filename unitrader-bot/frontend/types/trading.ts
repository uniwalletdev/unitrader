export interface OpenPosition {
  id: string;
  asset: string;
  exchange: string;
  side: "BUY" | "SELL";
  quantity: number;
  entryPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
  stopLoss: number;
  takeProfit: number;
  riskReward: string;
  timeOpen: string;
  confidence: number;
  status: "open" | "closing" | "closed";
}

export interface Trade {
  id: string;
  date: string;
  asset: string;
  exchange: string;
  side: "BUY" | "SELL";
  quantity: number;
  entryPrice: number;
  exitPrice: number | null;
  pnl: number | null;
  status: "open" | "closed" | "cancelled";
  reasoning: string;
  stopLoss: number;
  takeProfit: number;
  confidence: number;
  holdTime: string | null;
}

export interface AIAnalysis {
  asset: string;
  signalStrength: number;
  technicalScore: number;
  sentimentScore: number;
  rsi: number;
  macd: string;
  ma200: string;
  newsScore: number;
  socialSentiment: string;
  dailyLossUsed: number;
  positionSize: number;
  decision: "BUY" | "SELL" | "HOLD";
  confidence: number;
  reasoning: string;
  updatedAt: string;
}

export interface PerformanceStats {
  totalPnl: number;
  totalPnlPercent: number;
  winRate: number;
  avgWin: number;
  avgLoss: number;
  bestTrade: number;
  worstTrade: number;
  totalTrades: number;
  avgHoldTime: string;
  byAsset: {
    asset: string;
    pnl: number;
    winRate: number;
    trades: number;
  }[];
  byExchange: {
    exchange: string;
    pnl: number;
    trades: number;
  }[];
  chartData: {
    date: string;
    pnl: number;
    cumulative: number;
  }[];
}

export interface UserTradingSettings {
  tradingEnabled: boolean;
  riskLevel: "low" | "medium" | "high";
  maxTradeSize: number;
  dailyLossLimit: number;
  enabledAssets: string[];
  connectedExchanges: {
    exchange: string;
    isPaper: boolean;
    connectedAt: string;
  }[];
}

export interface CircuitBreakerAlert {
  active: boolean;
  reason: string;
  dailySummary: {
    trades: number;
    won: number;
    lost: number;
    netPnl: number;
  };
  resumesAt: string;
}

export interface TradeExecutionNotification {
  id: string;
  asset: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  exchange: string;
  reasoning: string;
  stopLoss: number;
  takeProfit: number;
  riskReward: string;
  confidence: number;
  executedAt: string;
}

