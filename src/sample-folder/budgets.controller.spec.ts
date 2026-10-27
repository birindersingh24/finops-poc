import { Test, TestingModule } from '@nestjs/testing';
import { BudgetsController } from './budgets.controller.js';
import { BudgetsService } from './budgets.service.js';

describe('BudgetsController', () => {
  let controller: BudgetsController;
  const budgetsService = { findAll: vi.fn() };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      controllers: [BudgetsController],
      providers: [{ provide: BudgetsService, useValue: budgetsService }],
    }).compile();

    controller = module.get<BudgetsController>(BudgetsController);
  });

  it('should delegate findAll to the service', () => {
    budgetsService.findAll.mockReturnValue([]);

    expect(controller.findAll()).toEqual([]);
    expect(budgetsService.findAll).toHaveBeenCalled();
  });
});
