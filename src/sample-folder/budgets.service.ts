import { Injectable } from '@nestjs/common';

@Injectable()
export class BudgetsService {
  findAll() {
    return [{ id: 1, name: 'Cloud', limit: 5000 }];
  }
}
